import json
import logging

import pytest

from datasentry import scheduler
from datasentry.exceptions import ConfigError


def _config(**overrides):
    return {
        "source_type": "csv",
        "csv_path": "data/orders.csv",
        "interval_seconds": 60,
        "config_path": "config/sales_rules.json",
        "database": "data/history.db",
        "output_root": "data/scheduled",
        "delimiter": ",",
        "encoding": "utf-8",
        "timeout": 5,
        "dry_run": False,
        "params": {},
        "headers": {},
        "log_file": "logs/scheduler.log",
        **overrides,
    }


def test_load_schedule_config_applies_defaults(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps({"source_type": "api", "api_url": "https://example.test/data", "interval_seconds": 120}), encoding="utf-8")

    config = scheduler.load_schedule_config(path)

    assert config["source_type"] == "api"
    assert config["database"] == "data/datasentry.db"
    assert config["timeout"] == 30.0
    assert config["headers"] == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"source_type": "csv", "csv_path": "orders.csv", "interval_seconds": 0},
        {"source_type": "api", "interval_seconds": 10},
        {"source_type": "ftp", "api_url": "ftp://example.test", "interval_seconds": 10},
        {"source_type": "csv", "csv_path": "orders.csv", "interval_seconds": True},
    ],
)
def test_load_schedule_config_rejects_invalid_settings(tmp_path, payload):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigError):
        scheduler.load_schedule_config(path)


def test_scheduled_csv_job_reuses_existing_pipeline(monkeypatch, caplog):
    expected = {"run_id": "run-csv", "status": "SUCCESS"}
    calls = []
    monkeypatch.setattr(scheduler, "run_etl_pipeline", lambda **kwargs: calls.append(kwargs) or expected)

    with caplog.at_level(logging.INFO, logger="datasentry.scheduler"):
        result = scheduler.run_scheduled_job(_config())

    assert result is expected
    assert calls[0]["source_path"] == "data/orders.csv"
    assert calls[0]["delimiter"] == ","
    assert "Scheduled execution started" in caplog.text
    assert "status=SUCCESS" in caplog.text


def test_scheduled_api_job_passes_api_options(monkeypatch):
    expected = {"run_id": "run-api", "status": "WARN"}
    calls = []
    monkeypatch.setattr(scheduler, "run_api_etl", lambda **kwargs: calls.append(kwargs) or expected)
    config = _config(
        source_type="api",
        api_url="https://example.test/data",
        params={"limit": 5},
        headers={"Accept": "application/json"},
    )

    assert scheduler.run_scheduled_job(config) is expected
    assert calls[0]["api_url"] == "https://example.test/data"
    assert calls[0]["params"] == {"limit": 5}
    assert calls[0]["headers"] == {"Accept": "application/json"}


def test_scheduled_job_logs_failure_without_success(monkeypatch, caplog):
    def fail(**kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(scheduler, "run_etl_pipeline", fail)
    with caplog.at_level(logging.INFO, logger="datasentry.scheduler"):
        result = scheduler.run_scheduled_job(_config())

    assert result is None
    assert "Scheduled execution failed" in caplog.text
    assert "source unavailable" in caplog.text
    assert "completed" not in caplog.text


def test_schedule_loop_uses_stop_event_without_waiting():
    class StopAfterFirstWait:
        def __init__(self):
            self.waited = []

        def is_set(self):
            return False

        def wait(self, seconds):
            self.waited.append(seconds)
            return True

    stop_event = StopAfterFirstWait()
    executions = []

    scheduler._run_schedule_loop(_config(interval_seconds=17), stop_event, lambda config: executions.append(config))

    assert len(executions) == 1
    assert stop_event.waited == [17]