from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exceptions import PersistenceError


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataSentryDatabase:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        source_fingerprint TEXT NOT NULL,
                        row_count INTEGER NOT NULL,
                        column_count INTEGER NOT NULL,
                        score REAL,
                        status TEXT NOT NULL,
                        config_identifier TEXT,
                        error_summary TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS check_results (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        check_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        column_name TEXT,
                        checked_count INTEGER NOT NULL,
                        failed_count INTEGER NOT NULL,
                        failure_percentage REAL,
                        message TEXT NOT NULL,
                        example_row_numbers TEXT,
                        FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_check_results_run_id ON check_results(run_id)")
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Database initialization failed: {self.db_path}. {exc}") from exc

    def insert_run(self, run_id: str, source_name: str, source_fingerprint: str, row_count: int, column_count: int, score: float | None, status: str, config_identifier: str | None, error_summary: str | None) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    """
                    INSERT INTO runs (id, created_at, source_name, source_fingerprint, row_count, column_count, score, status, config_identifier, error_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, utc_now_iso(), source_name, source_fingerprint, row_count, column_count, score, status, config_identifier, error_summary),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to persist run metadata for {run_id}. {exc}") from exc

    def insert_check_results(self, run_id: str, results: list[dict[str, Any]]) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                for result in results:
                    row_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO check_results (
                            id, run_id, check_id, name, status, severity, column_name, checked_count,
                            failed_count, failure_percentage, message, example_row_numbers
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row_id,
                            run_id,
                            result["check_id"],
                            result["name"],
                            result["status"],
                            result["severity"],
                            result.get("column"),
                            result["checked_count"],
                            result["failed_count"],
                            result.get("failure_percentage"),
                            result["message"],
                            json.dumps(result.get("example_row_numbers", [])),
                        ),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to persist check results for run {run_id}. {exc}") from exc

    def list_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, created_at, source_name, source_fingerprint, row_count, column_count, score, status, config_identifier, error_summary FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            run_row = conn.execute(
                "SELECT id, created_at, source_name, source_fingerprint, row_count, column_count, score, status, config_identifier, error_summary FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            checks = conn.execute(
                "SELECT check_id, name, status, severity, column_name, checked_count, failed_count, failure_percentage, message, example_row_numbers FROM check_results WHERE run_id = ? ORDER BY check_id",
                (run_id,),
            ).fetchall()
            result = dict(run_row)
            result["checks"] = [dict(row) for row in checks]
            return result

    def get_latest_run(self) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            run_row = conn.execute(
                "SELECT id, created_at, source_name, source_fingerprint, row_count, column_count, score, status, config_identifier, error_summary FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if run_row is None:
                return None
            return dict(run_row)
