from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .database import DataSentryDatabase
from .exceptions import ConfigError, DataSentryError, DataValidationError, PersistenceError, ReportError
from .orchestration import run_quality_check

DEFAULT_DB = Path("data/datasentry.db")
DEFAULT_REPORTS = Path("reports")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="datasentry", description="Data quality checker for CSV files.")
    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser("check", help="Profile and validate a CSV file.")
    check_parser.add_argument("csv_path", nargs="?", help="Path to a CSV file.")
    check_parser.add_argument("--config", default="config/example_rules.json", help="Path to JSON rule configuration.")
    check_parser.add_argument("--database", default=str(DEFAULT_DB), help="SQLite database path.")
    check_parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS), help="Directory for JSON/HTML reports.")
    check_parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: comma)")
    check_parser.add_argument("--encoding", default="utf-8", help="CSV encoding (default: utf-8)")

    history_parser = subparsers.add_parser("history", help="List recent runs.")
    history_parser.add_argument("--limit", type=int, default=10)
    history_parser.add_argument("--database", default=str(DEFAULT_DB), help="SQLite database path.")

    show_parser = subparsers.add_parser("show-run", help="Inspect a run by ID.")
    show_parser.add_argument("run_id")
    show_parser.add_argument("--database", default=str(DEFAULT_DB), help="SQLite database path.")

    parser.add_argument("--version", action="store_true", help="Display the version number.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None and args.version:
        from . import __version__
        print(__version__)
        return 0

    if args.command == "history":
        try:
            db = DataSentryDatabase(args.database)
            db.initialize()
            runs = db.list_recent_runs(limit=args.limit)
            if not runs:
                print("No runs found.")
                return 0
            for run in runs:
                print(f"{run['id']} | {run['created_at']} | {run['source_name']} | score={run['score']} | status={run['status']}")
            return 0
        except (PersistenceError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "show-run":
        try:
            db = DataSentryDatabase(args.database)
            db.initialize()
            run = db.get_run(args.run_id)
            if run is None:
                print(f"Unknown run ID: {args.run_id}")
                return 1
            print(json.dumps({k: v for k, v in run.items() if k != "checks"}, ensure_ascii=False, indent=2))
            print("--- checks ---")
            for check in run["checks"]:
                print(json.dumps(check, ensure_ascii=False))
            return 0
        except (PersistenceError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "check":
        if not args.csv_path:
            parser.error("A CSV path is required for check.")
            return 2
        try:
            result = run_quality_check(args.csv_path, args.config, args.database, args.reports_dir)
            print(f"Run ID: {result['run_id']}")
            print(f"Status: {result['status']} | Score: {result['score']}")
            print(f"JSON report: {result['report_json']}")
            print(f"HTML report: {result['report_html']}")
            return 0 if result["status"] != "FAIL" else 1
        except (DataValidationError, ConfigError, PersistenceError, ReportError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.version:
        from . import __version__
        print(__version__)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
