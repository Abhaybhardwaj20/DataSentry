from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_rules
from .csv_loader import load_csv
from .database import DataSentryDatabase
from .exceptions import ConfigError, DataSentryError, DataValidationError, ReportError
from .profiling import build_profile
from .reporting import write_html_report, write_json_report
from .rules import evaluate_rules
from .utils import file_fingerprint, safe_filename, source_label


def compute_score(results: list[dict[str, Any]]) -> float | None:
    applicable = [result for result in results if result["status"] not in {"SKIP"}]
    if not applicable:
        return None
    passed = sum(1 for result in applicable if result["status"] == "PASS")
    warned = sum(1 for result in applicable if result["status"] == "WARN")
    total = len(applicable)
    if warned:
        score = (passed + (warned * 0.5)) / total * 100
    else:
        score = (passed / total) * 100
    return round(score, 2)


def determine_status(results: list[dict[str, Any]]) -> str:
    if any(result.get("severity") == "ERROR" and result.get("status") in {"FAIL", "WARN"} for result in results):
        return "FAIL"
    if any(result.get("status") == "WARN" for result in results):
        return "WARN"
    if any(result.get("status") == "FAIL" for result in results):
        return "FAIL"
    return "PASS"


def run_quality_check(csv_path: str | Path, config_path: str | Path, database_path: str | Path, reports_dir: str | Path) -> dict[str, Any]:
    csv_path = Path(csv_path)
    config_path = Path(config_path)
    database_path = Path(database_path)
    reports_dir = Path(reports_dir)

    frame, fingerprint = load_csv(csv_path)
    config = load_rules(config_path)
    profile = build_profile(frame)
    results = evaluate_rules(frame, profile, config)
    score = compute_score(results)
    status = determine_status(results)

    run_id = str(uuid.uuid4())
    timestamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    source_name = source_label(csv_path)

    report_payload = {
        "run_id": run_id,
        "timestamp": timestamp,
        "source_name": source_name,
        "source_fingerprint": fingerprint,
        "row_count": profile["row_count"],
        "column_count": profile["column_count"],
        "score": score,
        "status": status,
        "profile": profile,
        "checks": results,
    }

    db = DataSentryDatabase(database_path)
    db.initialize()
    db.insert_run(run_id, source_name, fingerprint, profile["row_count"], profile["column_count"], score, status, config_path.name, None)
    db.insert_check_results(run_id, results)

    json_path = write_json_report(report_payload, reports_dir)
    html_path = write_html_report(report_payload, reports_dir)

    return {
        "run_id": run_id,
        "report_json": json_path,
        "report_html": html_path,
        "score": score,
        "status": status,
        "database": str(database_path),
        "source_name": source_name,
        "profile": profile,
        "checks": results,
    }
