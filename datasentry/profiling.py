from __future__ import annotations

from collections import Counter

import pandas as pd


def infer_column_type(series: pd.Series) -> str:
    values = series.dropna()
    if values.empty:
        return "all_null"

    stripped = values.map(lambda x: str(x).strip() if x is not None else "")
    if stripped.empty:
        return "all_null"

    numeric_values = pd.to_numeric(stripped, errors="coerce")
    if numeric_values.notna().all() and len(numeric_values) == len(values):
        return "numeric"

    bool_like = stripped.map(lambda x: x.lower() in {"true", "false", "yes", "no", "1", "0"})
    if bool_like.all():
        return "boolean"

    if stripped.map(lambda x: len(x) > 0).all():
        return "text"

    return "mixed"


def build_profile(frame: pd.DataFrame) -> dict:
    rows = len(frame)
    columns = list(frame.columns)
    duplicate_count = int(frame.duplicated(keep="first").sum())
    column_profiles = []

    for column in columns:
        series = frame[column]
        clean_values = series.map(lambda value: value.strip() if isinstance(value, str) else value)
        missing_mask = clean_values.isna() | clean_values.map(lambda value: isinstance(value, str) and value.strip() == "")
        missing_count = int(missing_mask.sum())
        non_missing = clean_values[~missing_mask]
        distinct_count = int(non_missing.nunique(dropna=True))

        numeric_values = pd.to_numeric(clean_values, errors="coerce")
        numeric_values = numeric_values[~numeric_values.isna()]
        stats = {
            "missing_count": missing_count,
            "missing_percentage": round((missing_count / rows) * 100, 2) if rows else None,
            "distinct_non_null_count": distinct_count,
            "inferred_type": infer_column_type(clean_values),
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "frequent_values": [],
        }

        if not numeric_values.empty:
            stats["min"] = float(numeric_values.min()) if not pd.isna(numeric_values.min()) else None
            stats["max"] = float(numeric_values.max()) if not pd.isna(numeric_values.max()) else None
            stats["mean"] = float(numeric_values.mean()) if not pd.isna(numeric_values.mean()) else None
            stats["median"] = float(numeric_values.median()) if not pd.isna(numeric_values.median()) else None

        if not non_missing.empty:
            value_counts = Counter(str(value) for value in non_missing.tolist())
            stats["frequent_values"] = [
                {"value": value, "count": count}
                for value, count in value_counts.most_common(5)
            ]

        column_profiles.append({"column": column, "stats": stats})

    return {
        "row_count": rows,
        "column_count": len(columns),
        "columns": columns,
        "column_profiles": column_profiles,
        "duplicate_full_row_count": duplicate_count,
    }
