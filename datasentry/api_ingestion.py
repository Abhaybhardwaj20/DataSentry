from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from .exceptions import DataValidationError
from .pipeline import run_etl_pipeline
from .utils import safe_filename


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        for key in ("data", "results", "items", "products", "orders", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                records = value
                break
        else:
            if payload and all(not isinstance(value, (dict, list)) for value in payload.values()):
                records = [payload]
            else:
                raise DataValidationError(
                    "API response does not contain a list of records in a recognized key such as 'data', 'results', or 'items'."
                )
    else:
        raise DataValidationError(f"Unexpected API response format: {type(payload).__name__}")

    if not records:
        raise DataValidationError("API response is empty; no records were returned.")

    return [record for record in records if isinstance(record, dict)]


def fetch_api_records(url: str, timeout: float = 30, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> pd.DataFrame:
    if not url or not isinstance(url, str):
        raise DataValidationError("An API URL is required to fetch data.")

    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise DataValidationError(f"API request to {url} timed out after {timeout} seconds.") from exc
    except requests.HTTPError as exc:
        status_code = getattr(response, "status_code", "unknown")
        raise DataValidationError(f"Failed to fetch API data from {url}: HTTP {status_code}. {exc}") from exc
    except requests.RequestException as exc:
        raise DataValidationError(f"Failed to fetch API data from {url}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise DataValidationError(f"API response from {url} is not valid JSON.") from exc

    records = _extract_records(payload)
    if not records:
        raise DataValidationError(f"API response from {url} did not include any usable records.")

    frame = pd.json_normalize(records)
    if frame.empty:
        raise DataValidationError(f"API response from {url} produced an empty table after normalization.")

    return frame


def _default_source_name(api_url: str) -> str:
    parsed = urlparse(api_url)
    name = parsed.path.strip("/").split("/")[-1] if parsed.path.strip("/") else "api_source"
    return safe_filename(name or "api_source")


def _pick_value(frame: pd.DataFrame, keys: tuple[str, ...], default: Any) -> Any:
    for key in keys:
        if key in frame.columns:
            return frame[key]
    if isinstance(default, (list, tuple, pd.Series)):
        return pd.Series(default, index=frame.index)
    return pd.Series([default] * len(frame), index=frame.index)


def _utc_today_iso() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")


def standardize_api_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    standardized = pd.DataFrame(index=frame.index)
    standardized["order_id"] = _pick_value(frame, ("order_id", "id"), default=list(range(len(frame))))
    standardized["customer_name"] = _pick_value(frame, ("customer_name", "name", "customerName", "title"), default="API Customer")
    standardized["email"] = _pick_value(frame, ("email", "customer_email", "emailAddress"), default=[f"customer{index}@example.com" for index in range(len(frame))])
    standardized["order_date"] = _pick_value(frame, ("order_date", "createdAt", "date"), default=_utc_today_iso())
    standardized["product"] = _pick_value(frame, ("product", "title", "name"), default="API Product")
    standardized["quantity"] = pd.to_numeric(_pick_value(frame, ("quantity",), default=1), errors="coerce").fillna(1)
    standardized["unit_price"] = pd.to_numeric(_pick_value(frame, ("unit_price", "price"), default=0), errors="coerce").fillna(0)
    standardized["status"] = _pick_value(frame, ("status", "state"), default="Completed")
    standardized["city"] = _pick_value(frame, ("city", "location", "category"), default="Unknown")

    standardized["customer_name"] = standardized["customer_name"].fillna("API Customer")
    standardized["email"] = standardized["email"].fillna("customer@example.com")
    standardized["order_date"] = standardized["order_date"].fillna(_utc_today_iso())
    standardized["product"] = standardized["product"].fillna("API Product")
    standardized["status"] = standardized["status"].fillna("Completed")
    standardized["city"] = standardized["city"].fillna("Unknown")

    standardized["order_id"] = standardized["order_id"].astype(str)
    standardized["quantity"] = pd.to_numeric(standardized["quantity"], errors="coerce").fillna(1)
    standardized["unit_price"] = pd.to_numeric(standardized["unit_price"], errors="coerce").fillna(0)

    return standardized


def run_api_etl(
    api_url: str,
    database_path: str | Path,
    output_root: str | Path,
    *,
    config_path: str | Path | None = None,
    timeout: float = 30,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    frame = fetch_api_records(api_url, timeout=timeout, params=params, headers=headers)
    standardized = standardize_api_frame(frame)

    source_name = _default_source_name(api_url)
    staging_dir = Path(output_root) / "api_source"
    staging_dir.mkdir(parents=True, exist_ok=True)
    source_path = staging_dir / f"{source_name}.csv"
    standardized.to_csv(source_path, index=False)

    result = run_etl_pipeline(
        source_path=source_path,
        database_path=database_path,
        output_root=output_root,
        config_path=config_path,
        dry_run=dry_run,
    )
    result["source_url"] = api_url
    result["source_name"] = source_name
    return result
