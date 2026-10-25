from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_rules
from .csv_loader import load_csv
from .database import DataSentryDatabase
from .exceptions import DataValidationError


def _normalize_column_name(column_name: Any) -> str:
    text = str(column_name).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "column"


def _as_clean_series(series: pd.Series) -> pd.Series:
    return series.map(lambda value: value.strip() if isinstance(value, str) else value)


def _clean_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    cleaned.columns = [_normalize_column_name(column) for column in cleaned.columns]

    for column in cleaned.columns:
        if cleaned[column].dtype == object:
            cleaned[column] = _as_clean_series(cleaned[column])

    return cleaned


def _default_rules() -> dict[str, Any]:
    candidates = [Path("config/sales_rules.json"), Path("config/example_rules.json")]
    for candidate in candidates:
        if candidate.exists():
            return load_rules(candidate)
    return {
        "schema_version": 1,
        "required_columns": [
            "order_id",
            "customer_name",
            "email",
            "order_date",
            "product",
            "quantity",
            "unit_price",
            "status",
            "city",
        ],
        "non_null_columns": [
            "order_id",
            "customer_name",
            "email",
            "order_date",
            "product",
            "quantity",
            "unit_price",
            "status",
            "city",
        ],
        "allowed_values": {"status": ["Completed", "Pending", "Cancelled"]},
        "numeric_ranges": {"quantity": {"min": 1, "max": 100}, "unit_price": {"min": 1, "max": 100000}},
        "expected_types": {"quantity": ["numeric"], "unit_price": ["numeric"]},
        "regex_patterns": {"email": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"},
        "duplicate_row_policy": "warn",
    }


def _validate_rows(frame: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), frame.copy()

    required_columns = config.get("required_columns", list(frame.columns))
    missing_columns = [column for column in required_columns if column not in frame.columns]
    if missing_columns:
        raise DataValidationError(f"Missing required columns for ETL: {', '.join(missing_columns)}")

    working = frame.copy()
    working["__valid__"] = True

    columns_to_check = config.get("non_null_columns", [])
    for column in columns_to_check:
        if column in working.columns:
            working["__valid__"] = working["__valid__"] & working[column].notna() & ~working[column].astype(str).str.strip().eq("")

    if "email" in working.columns:
        pattern = config.get("regex_patterns", {}).get("email")
        if pattern:
            regex = re.compile(pattern)
            working["__valid__"] = working["__valid__"] & working["email"].fillna("").astype(str).str.strip().map(lambda value: bool(regex.fullmatch(value)) if value else False)

    if "order_date" in working.columns:
        parsed_dates = pd.to_datetime(working["order_date"].astype(str).str.strip().str.replace("/", "-"), errors="coerce")
        working["__valid__"] = working["__valid__"] & parsed_dates.notna()

    for column, range_map in config.get("numeric_ranges", {}).items():
        if column not in working.columns:
            continue
        numeric_values = pd.to_numeric(working[column].astype(str).str.strip(), errors="coerce")
        lower = range_map.get("min")
        upper = range_map.get("max")
        if lower is not None:
            working["__valid__"] = working["__valid__"] & numeric_values.notna() & (numeric_values >= lower)
        if upper is not None:
            working["__valid__"] = working["__valid__"] & numeric_values.notna() & (numeric_values <= upper)

    if "status" in working.columns:
        allowed_states = set(str(value) for value in config.get("allowed_values", {}).get("status", []))
        if allowed_states:
            working["__valid__"] = working["__valid__"] & working["status"].astype(str).str.strip().isin(allowed_states)

    unique_columns = list(config.get("unique_columns", []))
    if "order_id" in working.columns and "order_id" not in unique_columns:
        unique_columns.append("order_id")
    for column in unique_columns:
        if column not in working.columns:
            continue
        values = working[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        eligible = working["__valid__"] & values.notna() & ~values.map(
            lambda value: isinstance(value, str) and value == ""
        )
        duplicate_indexes = values.loc[eligible][values.loc[eligible].duplicated(keep="first")].index
        working.loc[duplicate_indexes, "__valid__"] = False

    valid_rows = working.loc[working["__valid__"]].drop(columns=["__valid__"]).copy()
    rejected_rows = working.loc[~working["__valid__"]].drop(columns=["__valid__"]).copy()

    if config.get("duplicate_row_policy", "warn") in {"warn", "error"}:
        deduped = valid_rows.drop_duplicates()
        rejected_rows = pd.concat([rejected_rows, valid_rows.loc[~valid_rows.index.isin(deduped.index)]], ignore_index=True)
        valid_rows = deduped.copy()

    return valid_rows.reset_index(drop=True), rejected_rows.reset_index(drop=True)


GOLD_COLUMNS = [
    "city",
    "status",
    "order_count",
    "gross_revenue",
    "average_order_value",
    "aggregation",
    "product",
    "order_date",
    "total_valid_orders",
    "total_sales_revenue",
]


def _build_gold_layer(valid_rows: pd.DataFrame) -> pd.DataFrame:
    if valid_rows.empty:
        return pd.DataFrame(columns=GOLD_COLUMNS)

    gold = valid_rows.copy()
    gold["order_id"] = gold["order_id"].map(lambda value: value.strip() if isinstance(value, str) else value)
    gold["order_date"] = pd.to_datetime(gold["order_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    gold["quantity"] = pd.to_numeric(gold["quantity"], errors="coerce")
    gold["unit_price"] = pd.to_numeric(gold["unit_price"], errors="coerce")
    usable = (
        gold["order_id"].notna()
        & gold["order_id"].astype(str).str.strip().ne("")
        & gold["order_date"].notna()
        & gold["quantity"].map(lambda value: pd.notna(value) and math.isfinite(float(value)) and value > 0)
        & gold["unit_price"].map(lambda value: pd.notna(value) and math.isfinite(float(value)) and value > 0)
    )
    gold = gold.loc[usable].drop_duplicates(subset=["order_id"], keep="first").copy()
    if gold.empty:
        return pd.DataFrame(columns=GOLD_COLUMNS)

    gold["gross_revenue"] = gold["quantity"] * gold["unit_price"]
    dimensions = ["city", "status", "product", "order_date"]
    aggregations = [
        ("overall", []),
        ("product", ["product"]),
        ("city", ["city"]),
        ("status", ["status"]),
        ("daily", ["order_date"]),
        ("city_status", ["city", "status"]),
    ]
    summaries = []

    for aggregation, group_columns in aggregations:
        if group_columns:
            grouped = gold.groupby(group_columns, dropna=False, as_index=False).agg(
                order_count=("order_id", "nunique"),
                gross_revenue=("gross_revenue", "sum"),
            )
        else:
            grouped = pd.DataFrame(
                [{"order_count": int(gold["order_id"].nunique()), "gross_revenue": float(gold["gross_revenue"].sum())}]
            )

        grouped["average_order_value"] = grouped["gross_revenue"] / grouped["order_count"]
        grouped["aggregation"] = aggregation
        for dimension in dimensions:
            if dimension not in grouped.columns:
                grouped[dimension] = None
        grouped["total_valid_orders"] = grouped["order_count"]
        grouped["total_sales_revenue"] = grouped["gross_revenue"]
        summaries.append(grouped[GOLD_COLUMNS])

    return pd.concat(summaries, ignore_index=True)[GOLD_COLUMNS]


def _write_layer_csv(frame: pd.DataFrame, layer_dir: Path, run_id: str, prefix: str) -> str:
    layer_dir.mkdir(parents=True, exist_ok=True)
    path = layer_dir / f"{run_id}_{prefix}.csv"
    frame.to_csv(path, index=False)
    return str(path)


def run_etl_pipeline(
    source_path: str | Path,
    database_path: str | Path,
    output_root: str | Path,
    *,
    config_path: str | Path | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8",
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(source_path)
    database = Path(database_path)
    output_root = Path(output_root)

    if not source.exists():
        raise DataValidationError(f"Source file does not exist: {source}")

    raw_df, source_fingerprint = load_csv(source, delimiter=delimiter, encoding=encoding)
    if raw_df.empty:
        raise DataValidationError(f"Source file is empty: {source}")

    config = load_rules(config_path) if config_path else _default_rules()
    bronze_df = _clean_dataframe(raw_df)

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    raw_dir = output_root / "raw"
    bronze_dir = output_root / "bronze"
    silver_dir = output_root / "silver"
    gold_dir = output_root / "gold"

    raw_path = _write_layer_csv(raw_df, raw_dir, run_id, "raw") if not dry_run else ""
    bronze_path = _write_layer_csv(bronze_df, bronze_dir, run_id, "bronze") if not dry_run else ""

    valid_df, rejected_df = _validate_rows(bronze_df, config)
    silver_path = _write_layer_csv(valid_df, silver_dir, run_id, "silver") if not dry_run else ""

    gold_df = _build_gold_layer(valid_df)
    gold_path = _write_layer_csv(gold_df, gold_dir, run_id, "gold") if not dry_run else ""

    ended_at = datetime.now(timezone.utc)
    duration_seconds = round((ended_at - started_at).total_seconds(), 3)
    status = "SUCCESS" if rejected_df.empty else "WARN"

    summary = {
        "run_id": run_id,
        "source_name": source.name,
        "source_fingerprint": source_fingerprint,
        "input_rows": int(len(raw_df)),
        "valid_rows": int(len(valid_df)),
        "rejected_rows": int(len(rejected_df)),
        "status": status,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": duration_seconds,
        "raw_path": raw_path,
        "bronze_path": bronze_path,
        "silver_path": silver_path,
        "gold_path": gold_path,
        "database": str(database),
        "rejected_preview": rejected_df.head(10).to_dict(orient="records"),
    }

    if not dry_run:
        database_obj = DataSentryDatabase(database)
        database_obj.initialize()
        database_obj.insert_pipeline_run(
            run_id=run_id,
            source_name=source.name,
            source_fingerprint=source_fingerprint,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_seconds=duration_seconds,
            input_rows=int(len(raw_df)),
            valid_rows=int(len(valid_df)),
            rejected_rows=int(len(rejected_df)),
            status=status,
            raw_path=raw_path,
            bronze_path=bronze_path,
            silver_path=silver_path,
            gold_path=gold_path,
            error_details=(json.dumps(rejected_df.head(10).to_dict(orient="records"), ensure_ascii=False) if not rejected_df.empty else None),
        )

    return summary
