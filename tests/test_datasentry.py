import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from datasentry.cli import main
from datasentry.config import load_rules
from datasentry.csv_loader import load_csv
from datasentry.dashboard import compute_dashboard_summary
from datasentry.database import DataSentryDatabase
from datasentry.orchestration import compute_score
from datasentry.profiling import build_profile
from datasentry.reporting import write_html_report, write_json_report
from datasentry.rules import evaluate_rules


def test_load_csv_detects_duplicate_column_names(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("id,name,id\n1,Alice,1\n2,Bob,2\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_csv(csv_path)


def test_profile_reports_missing_and_duplicates():
    df = pd.DataFrame(
        {
            "customer_id": ["A", "A", "B", "B"],
            "age": ["20", "20", "30", "40"],
        }
    )
    profile = build_profile(df)
    assert profile["row_count"] == 4
    assert profile["column_count"] == 2
    assert profile["duplicate_full_row_count"] == 1
    assert profile["column_profiles"][0]["stats"]["missing_count"] == 0


def test_required_column_rule_reports_missing_and_passes():
    df = pd.DataFrame({"name": ["Alice", "Bob"]})
    profile = build_profile(df)
    config = {"schema_version": 1, "required_columns": ["name", "email"]}
    results = evaluate_rules(df, profile, config)
    missing_result = [r for r in results if r["check_id"] == "required_columns_missing"][0]
    assert missing_result["status"] == "FAIL"
    assert "email" in missing_result["message"]

    df2 = pd.DataFrame({"name": ["Alice", "Bob"], "email": ["a@b.com", "c@d.com"]})
    results2 = evaluate_rules(df2, build_profile(df2), {"schema_version": 1, "required_columns": ["name", "email"]})
    passed = [r for r in results2 if r["column"] == "name" and r["status"] == "PASS"][0]
    assert passed["status"] == "PASS"


def test_duplicate_rows_policy_and_score_range():
    df = pd.DataFrame({"id": [1, 1, 2], "value": ["x", "x", "y"]})
    profile = build_profile(df)
    config = {"schema_version": 1, "duplicate_row_policy": "warn"}
    results = evaluate_rules(df, profile, config)
    duplicate_result = [r for r in results if r["check_id"] == "duplicate_rows"][0]
    assert duplicate_result["failed_count"] == 1

    score = compute_score(results)
    assert 0 <= score <= 100


def test_invalid_json_configuration_is_rejected(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text('{"schema_version": 1,', encoding="utf-8")
    with pytest.raises(Exception):
        load_rules(config_path)


def test_html_report_escapes_special_characters(tmp_path):
    payload = {
        "run_id": "run-1",
        "timestamp": "2024-01-01T00:00:00Z",
        "source_name": "sample & <script>",
        "row_count": 1,
        "column_count": 1,
        "score": 90,
        "status": "PASS",
        "profile": {"column_profiles": [{"column": "name", "stats": {"inferred_type": "text", "missing_count": 0, "missing_percentage": 0.0, "distinct_non_null_count": 1, "min": None, "max": None, "mean": None, "median": None}}]},
        "checks": [],
    }
    output_path = tmp_path / "reports"
    path = write_html_report(payload, output_path)
    content = Path(path).read_text(encoding="utf-8")
    assert "&amp;" in content
    assert "&lt;script&gt;" in content or "&lt;script&gt;" in content


def test_json_report_uses_standard_types(tmp_path):
    payload = {"run_id": "run-2", "timestamp": "2024-01-01T00:00:00Z", "source_name": "name", "row_count": 2, "column_count": 1, "score": 50, "status": "WARN", "profile": {}, "checks": []}
    path = write_json_report(payload, tmp_path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["run_id"] == "run-2"
    assert data["score"] == 50


def test_database_round_trip(tmp_path):
    db_path = tmp_path / "runs.db"
    db = DataSentryDatabase(db_path)
    db.initialize()
    db.insert_run("run-abc", "demo.csv", "fingerprint", 2, 2, 88.0, "PASS", "rules.json", "")
    db.insert_check_results("run-abc", [{"check_id": "check-1", "name": "Sample", "status": "PASS", "severity": "INFO", "column": "name", "checked_count": 2, "failed_count": 0, "failure_percentage": 0.0, "message": "ok", "example_row_numbers": [1, 2]}])
    run = db.get_run("run-abc")
    assert run is not None
    assert run["source_name"] == "demo.csv"
    assert len(run["checks"]) == 1


def test_cli_check_and_history(tmp_path):
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text("customer_id,name,email\nC1,Alice,alice@example.com\nC2,Bob,bob@example.com\n", encoding="utf-8")
    config_path = tmp_path / "rules.json"
    config_path.write_text(json.dumps({"schema_version": 1, "required_columns": ["customer_id", "name", "email"], "duplicate_row_policy": "warn"}), encoding="utf-8")
    db_path = tmp_path / "db" / "history.db"
    reports_dir = tmp_path / "reports"
    rc = main(["check", str(csv_path), "--config", str(config_path), "--database", str(db_path), "--reports-dir", str(reports_dir)])
    assert rc in {0, 1}
    history_rc = main(["history", "--database", str(db_path), "--limit", "10"])
    assert history_rc == 0


def test_version_and_help_without_db(tmp_path):
    result = subprocess.run([sys.executable, "-m", "datasentry", "--version"], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"


def test_zero_applicable_checks_returns_none():
    assert compute_score([]) is None


def test_dashboard_summary_uses_real_database_history(tmp_path):
    db_path = tmp_path / "dashboard.db"
    db = DataSentryDatabase(db_path)
    db.initialize()
    db.insert_run("run-1", "good.csv", "abc", 3, 2, 100.0, "PASS", "rules.json", None)
    db.insert_run("run-2", "bad.csv", "def", 4, 2, 60.0, "FAIL", "rules.json", None)
    db.insert_check_results(
        "run-2",
        [
            {
                "check_id": "required_columns",
                "name": "Required columns",
                "status": "FAIL",
                "severity": "ERROR",
                "column": "email",
                "checked_count": 1,
                "failed_count": 1,
                "failure_percentage": 100.0,
                "message": "Missing email",
                "example_row_numbers": [1],
            }
        ],
    )

    summary = compute_dashboard_summary(db_path)
    assert summary["total_runs"] == 2
    assert summary["latest_score"] == 60.0
    assert summary["latest_status"] == "FAIL"
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["total_violations"] == 1
