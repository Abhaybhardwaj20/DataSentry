from __future__ import annotations

import json
import logging
import math
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .api_ingestion import run_api_etl
from .exceptions import ConfigError
from .pipeline import run_etl_pipeline

LOGGER = logging.getLogger(__name__)


def load_schedule_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Unable to load scheduler configuration from {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise ConfigError("Scheduler configuration must be a JSON object.")

    source_type = config.get("source_type")
    if not isinstance(source_type, str) or source_type not in {"csv", "api"}:
        raise ConfigError("Scheduler source_type must be either 'csv' or 'api'.")
    source_key = "csv_path" if source_type == "csv" else "api_url"
    if not isinstance(config.get(source_key), str) or not config[source_key].strip():
        raise ConfigError(f"Scheduler configuration requires a non-empty '{source_key}'.")

    interval = config.get("interval_seconds")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ConfigError("Scheduler interval_seconds must be a finite number greater than zero.")

    defaults = {
        "config_path": "config/sales_rules.json",
        "database": "data/datasentry.db",
        "output_root": "data/scheduled",
        "delimiter": ",",
        "encoding": "utf-8",
        "timeout": 30.0,
        "dry_run": False,
        "params": {},
        "headers": {},
        "log_file": "logs/datasentry-scheduler.log",
    }
    normalized = {**defaults, **config}

    for key in ("config_path", "database", "output_root", "delimiter", "encoding", "log_file"):
        if not isinstance(normalized[key], str) or not normalized[key].strip():
            raise ConfigError(f"Scheduler setting '{key}' must be a non-empty string.")
    if isinstance(normalized["timeout"], bool) or not isinstance(normalized["timeout"], (int, float)) or not math.isfinite(normalized["timeout"]) or normalized["timeout"] <= 0:
        raise ConfigError("Scheduler timeout must be a finite number greater than zero.")
    if not isinstance(normalized["dry_run"], bool):
        raise ConfigError("Scheduler setting 'dry_run' must be true or false.")
    for key in ("params", "headers"):
        if not isinstance(normalized[key], dict):
            raise ConfigError(f"Scheduler setting '{key}' must be a JSON object.")

    return normalized


def run_scheduled_job(config: dict[str, Any]) -> dict[str, Any] | None:
    started_at = datetime.now(timezone.utc).isoformat()
    source_type = config["source_type"]
    source = config["csv_path"] if source_type == "csv" else config["api_url"]
    LOGGER.info("Scheduled execution started at %s | source_type=%s | source=%s", started_at, source_type, source)

    try:
        common = {
            "database_path": config["database"],
            "output_root": config["output_root"],
            "config_path": config["config_path"],
            "dry_run": config["dry_run"],
        }
        if source_type == "csv":
            result = run_etl_pipeline(
                source_path=config["csv_path"],
                delimiter=config["delimiter"],
                encoding=config["encoding"],
                **common,
            )
        elif source_type == "api":
            result = run_api_etl(
                api_url=config["api_url"],
                timeout=config["timeout"],
                params=config["params"],
                headers=config["headers"],
                **common,
            )
        else:
            raise ConfigError(f"Unsupported scheduler source_type: {source_type}")

        status = result.get("status")
        completed_at = datetime.now(timezone.utc).isoformat()
        if status not in {"SUCCESS", "WARN"}:
            raise RuntimeError(f"ETL returned unexpected status: {status!r}")
        if status == "WARN":
            LOGGER.warning("Scheduled execution completed at %s | status=WARN | run_id=%s", completed_at, result.get("run_id"))
        else:
            LOGGER.info("Scheduled execution completed at %s | status=SUCCESS | run_id=%s", completed_at, result.get("run_id"))
        return result
    except Exception:
        LOGGER.exception("Scheduled execution failed at %s | source_type=%s | source=%s", datetime.now(timezone.utc).isoformat(), source_type, source)
        return None


def _run_schedule_loop(
    config: dict[str, Any],
    stop_event: threading.Event,
    execute: Callable[[dict[str, Any]], dict[str, Any] | None] = run_scheduled_job,
) -> None:
    while not stop_event.is_set():
        execute(config)
        if stop_event.wait(config["interval_seconds"]):
            break


def run_scheduler(config_path: str | Path) -> None:
    config = load_schedule_config(config_path)
    log_path = Path(config["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )

    LOGGER.info(
        "Scheduler started | source_type=%s | interval_seconds=%s | log_file=%s",
        config["source_type"],
        config["interval_seconds"],
        log_path,
    )
    stop_event = threading.Event()
    previous_handler = signal.getsignal(signal.SIGINT)

    def request_stop(signum: int, frame: Any) -> None:
        LOGGER.info("Shutdown requested; the current ETL run will finish before stopping.")
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    try:
        _run_schedule_loop(config, stop_event)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        LOGGER.info("Scheduler stopped.")