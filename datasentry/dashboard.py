from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .database import DataSentryDatabase


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database file does not exist: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def compute_dashboard_summary(db_path: str | Path) -> dict[str, Any]:
    """Return summary metrics for the latest run and overall run history."""
    db = DataSentryDatabase(db_path)
    runs = db.list_recent_runs(limit=1000)

    if not runs:
        return {
            "total_runs": 0,
            "latest_run_id": None,
            "latest_score": None,
            "latest_status": None,
            "latest_source": None,
            "total_violations": 0,
            "pass_count": 0,
            "fail_count": 0,
            "warn_count": 0,
            "history": [],
        }

    latest = runs[0]
    latest_run = db.get_run(latest["id"])
    latest_status = str(latest.get("status") or "UNKNOWN").upper()
    total_violations = 0
    if latest_run:
        for check in latest_run.get("checks", []):
            total_violations += int(check.get("failed_count") or 0)

    pass_count = sum(1 for run in runs if str(run.get("status") or "").upper() == "PASS")
    fail_count = sum(1 for run in runs if str(run.get("status") or "").upper() == "FAIL")
    warn_count = sum(1 for run in runs if str(run.get("status") or "").upper() == "WARN")

    return {
        "total_runs": len(runs),
        "latest_run_id": latest.get("id"),
        "latest_score": latest.get("score"),
        "latest_status": latest_status,
        "latest_source": latest.get("source_name"),
        "total_violations": total_violations,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "history": runs,
    }


def get_run_history(db_path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, source_name, row_count, column_count, score, status
            FROM runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_rule_breakdown(db_path: str | Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT check_id, name, SUM(failed_count) AS total_failures
            FROM check_results
            GROUP BY check_id, name
            ORDER BY total_failures DESC, check_id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_run_details(db_path: str | Path, run_id: str) -> dict[str, Any] | None:
    db = DataSentryDatabase(db_path)
    return db.get_run(run_id)


def get_run_status_counts(db_path: str | Path) -> dict[str, int]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM runs GROUP BY status ORDER BY status"
        ).fetchall()
        return {str(row["status"]).upper(): int(row["count"]) for row in rows}


def load_dashboard_data(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "summary": {
                "total_runs": 0,
                "latest_run_id": None,
                "latest_score": None,
                "latest_status": None,
                "latest_source": None,
                "total_violations": 0,
                "pass_count": 0,
                "fail_count": 0,
                "warn_count": 0,
                "history": [],
            },
            "history": [],
            "breakdown": [],
            "status_counts": {},
        }

    summary = compute_dashboard_summary(path)
    history = get_run_history(path)
    breakdown = get_rule_breakdown(path)
    status_counts = get_run_status_counts(path)

    return {
        "summary": summary,
        "history": history,
        "breakdown": breakdown,
        "status_counts": status_counts,
    }
