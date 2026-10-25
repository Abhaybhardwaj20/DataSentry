from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .api_ingestion import run_api_etl
from .database import DataSentryDatabase
from .exceptions import ConfigError, DataSentryError, DataValidationError, PersistenceError, ReportError
from .orchestration import run_quality_check
from .pipeline import run_etl_pipeline
from .scheduler import run_scheduler

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

    etl_parser = subparsers.add_parser("etl", help="Run the local ETL workflow across raw, bronze, silver, and gold layers.")
    etl_parser.add_argument("csv_path", nargs="?", help="Path to a CSV file to extract.")
    etl_parser.add_argument("--config", default="config/sales_rules.json", help="Path to JSON rule configuration.")
    etl_parser.add_argument("--database", default=str(DEFAULT_DB), help="SQLite database path for ETL run history.")
    etl_parser.add_argument("--output-root", default="data/etl", help="Root directory for raw, bronze, silver, and gold outputs.")
    etl_parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: comma)")
    etl_parser.add_argument("--encoding", default="utf-8", help="CSV encoding (default: utf-8)")
    etl_parser.add_argument("--api-url", help="Public API JSON endpoint to ingest instead of a CSV file.")
    etl_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout for API requests in seconds.")
    etl_parser.add_argument("--dry-run", action="store_true", help="Validate and summarize the pipeline without writing output files.")

    api_parser = subparsers.add_parser("api", help="Fetch JSON records from a public API and run the ETL workflow.")
    api_parser.add_argument("api_url", help="Public API JSON endpoint.")
    api_parser.add_argument("--config", default="config/sales_rules.json", help="Path to JSON rule configuration.")
    api_parser.add_argument("--database", default=str(DEFAULT_DB), help="SQLite database path for ETL run history.")
    api_parser.add_argument("--output-root", default="data/etl", help="Root directory for raw, bronze, silver, and gold outputs.")
    api_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout for API requests in seconds.")
    api_parser.add_argument("--dry-run", action="store_true", help="Validate and summarize the pipeline without writing output files.")

    schedule_parser = subparsers.add_parser("schedule", help="Run an ETL job repeatedly using a JSON schedule configuration.")
    schedule_parser.add_argument("--config", default="config/schedule.json", help="Path to the scheduler JSON configuration.")

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
            pipeline_runs = db.list_recent_pipeline_runs(limit=args.limit)
            combined = sorted(
                [
                    {**run, "kind": "quality"}
                    for run in runs
                ] + [
                    {**run, "kind": "etl"}
                    for run in pipeline_runs
                ],
                key=lambda run: run.get("created_at") or run.get("started_at") or "",
                reverse=True,
            )[: args.limit]
            if not combined:
                print("No runs found.")
                return 0
            for run in combined:
                if run["kind"] == "etl":
                    print(f"{run['id']} | {run['created_at']} | {run['source_name']} | ETL | valid={run['valid_rows']} rejected={run['rejected_rows']} | status={run['status']}")
                else:
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
                run = db.get_pipeline_run(args.run_id)
            if run is None:
                print(f"Unknown run ID: {args.run_id}")
                return 1
            if "checks" in run:
                print(json.dumps({k: v for k, v in run.items() if k != "checks"}, ensure_ascii=False, indent=2))
                print("--- checks ---")
                for check in run["checks"]:
                    print(json.dumps(check, ensure_ascii=False))
            else:
                print(json.dumps(run, ensure_ascii=False, indent=2))
            return 0
        except (PersistenceError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "schedule":
        try:
            run_scheduler(args.config)
            return 0
        except (ConfigError, OSError) as exc:
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

    if args.command == "etl":
        if args.api_url:
            try:
                result = run_api_etl(
                    api_url=args.api_url,
                    database_path=args.database,
                    output_root=args.output_root,
                    config_path=args.config,
                    timeout=args.timeout,
                    dry_run=args.dry_run,
                )
                print(f"ETL Run ID: {result['run_id']}")
                print(f"Status: {result['status']} | Input rows: {result['input_rows']} | Valid rows: {result['valid_rows']} | Rejected rows: {result['rejected_rows']}")
                print(f"Raw layer: {result['raw_path'] or 'dry-run'}")
                print(f"Bronze layer: {result['bronze_path'] or 'dry-run'}")
                print(f"Silver layer: {result['silver_path'] or 'dry-run'}")
                print(f"Gold layer: {result['gold_path'] or 'dry-run'}")
                return 0 if result["status"] in {"SUCCESS", "WARN"} else 1
            except (DataValidationError, ConfigError, PersistenceError, OSError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1

        if not args.csv_path:
            parser.error("A CSV path or --api-url is required for etl.")
            return 2
        try:
            result = run_etl_pipeline(
                source_path=args.csv_path,
                database_path=args.database,
                output_root=args.output_root,
                config_path=args.config,
                delimiter=args.delimiter,
                encoding=args.encoding,
                dry_run=args.dry_run,
            )
            print(f"ETL Run ID: {result['run_id']}")
            print(f"Status: {result['status']} | Input rows: {result['input_rows']} | Valid rows: {result['valid_rows']} | Rejected rows: {result['rejected_rows']}")
            print(f"Raw layer: {result['raw_path'] or 'dry-run'}")
            print(f"Bronze layer: {result['bronze_path'] or 'dry-run'}")
            print(f"Silver layer: {result['silver_path'] or 'dry-run'}")
            print(f"Gold layer: {result['gold_path'] or 'dry-run'}")
            return 0 if result["status"] in {"SUCCESS", "WARN"} else 1
        except (DataValidationError, ConfigError, PersistenceError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "api":
        try:
            result = run_api_etl(
                api_url=args.api_url,
                database_path=args.database,
                output_root=args.output_root,
                config_path=args.config,
                timeout=args.timeout,
                dry_run=args.dry_run,
            )
            print(f"ETL Run ID: {result['run_id']}")
            print(f"Status: {result['status']} | Input rows: {result['input_rows']} | Valid rows: {result['valid_rows']} | Rejected rows: {result['rejected_rows']}")
            print(f"Source URL: {result['source_url']}")
            print(f"Raw layer: {result['raw_path'] or 'dry-run'}")
            print(f"Bronze layer: {result['bronze_path'] or 'dry-run'}")
            print(f"Silver layer: {result['silver_path'] or 'dry-run'}")
            print(f"Gold layer: {result['gold_path'] or 'dry-run'}")
            return 0 if result["status"] in {"SUCCESS", "WARN"} else 1
        except (DataValidationError, ConfigError, PersistenceError, OSError) as exc:
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
