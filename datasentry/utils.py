from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
from typing import Any


def ensure_parent_dir(path: str | Path) -> Path:
    target = Path(path)
    if target.exists() and target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.parent
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in name)
    cleaned = cleaned.strip("._") or "report"
    return cleaned


def source_label(source_path: str | Path) -> str:
    return str(Path(source_path).name) if str(source_path) else "unknown-source"


def file_fingerprint(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def normalize_for_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("Non-finite numbers are not allowed in JSON output.")
        return value
    if isinstance(value, dict):
        return {str(k): normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_for_json(v) for v in value]
    if hasattr(value, "item"):
        try:
            return normalize_for_json(value.item())
        except Exception:
            return str(value)
    return str(value)


def html_escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def json_dumps(obj: Any) -> str:
    return json.dumps(normalize_for_json(obj), ensure_ascii=False, allow_nan=False, indent=2)


def format_ratio(part: int, total: int) -> float | None:
    if total == 0:
        return None
    return round((part / total) * 100, 2)


def strip_missing(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return value
