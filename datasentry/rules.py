from __future__ import annotations

import re
from typing import Any

import pandas as pd

VALID_STATUSES = {"PASS", "FAIL", "WARN", "SKIP"}
VALID_SEVERITIES = {"ERROR", "WARNING", "INFO"}


def build_result(check_id: str, name: str, status: str, severity: str, message: str, *, column: str | None = None, checked_count: int = 0, failed_count: int = 0, examples: list[int] | None = None, failure_ratio: float | None = None) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Illegal status: {status}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"Illegal severity: {severity}")
    if checked_count == 0 and status in {"PASS", "FAIL", "WARN"}:
        failure_ratio = 0.0 if status in {"PASS"} else 100.0
    return {
        "check_id": check_id,
        "name": name,
        "status": status,
        "severity": severity,
        "column": column,
        "checked_count": checked_count,
        "failed_count": failed_count,
        "failure_percentage": failure_ratio if failure_ratio is not None else (round((failed_count / checked_count) * 100, 2) if checked_count else None),
        "message": message,
        "example_row_numbers": list(examples or []),
    }


def evaluate_rules(frame: pd.DataFrame, profile: dict, config: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []

    empty_dataset = profile["row_count"] == 0
    rules.append(build_result(
        "empty_dataset",
        "Empty dataset",
        "FAIL" if empty_dataset else "PASS",
        "ERROR" if empty_dataset else "INFO",
        "Dataset is empty." if empty_dataset else "Dataset has rows.",
        checked_count=profile["row_count"],
        failed_count=1 if empty_dataset else 0,
        examples=[1] if empty_dataset else [],
        failure_ratio=100.0 if empty_dataset else 0.0,
    ))

    minimum_rows = config.get("minimum_rows")
    if minimum_rows is not None:
        count = profile["row_count"]
        failed = count < minimum_rows
        rules.append(build_result(
            "minimum_rows",
            "Minimum row count",
            "FAIL" if failed else "PASS",
            "ERROR" if failed else "INFO",
            f"Dataset has {count} rows; minimum required is {minimum_rows}.",
            checked_count=count,
            failed_count=1 if failed else 0,
            examples=[] if not failed else [count],
            failure_ratio=100.0 if failed else 0.0,
        ))

    maximum_rows = config.get("maximum_rows")
    if maximum_rows is not None:
        count = profile["row_count"]
        failed = count > maximum_rows
        rules.append(build_result(
            "maximum_rows",
            "Maximum row count",
            "FAIL" if failed else "PASS",
            "ERROR" if failed else "INFO",
            f"Dataset has {count} rows; maximum allowed is {maximum_rows}.",
            checked_count=count,
            failed_count=1 if failed else 0,
            examples=[] if not failed else [count],
            failure_ratio=100.0 if failed else 0.0,
        ))

    for column in config.get("required_columns", []):
        present = column in frame.columns
        rules.append(build_result(
            "required_columns" if present else "required_columns_missing",
            "Required columns",
            "PASS" if present else "FAIL",
            "INFO" if present else "ERROR",
            f"Required column '{column}' is present." if present else f"Required column '{column}' is missing.",
            column=column,
            checked_count=1,
            failed_count=0 if present else 1,
            examples=[],
            failure_ratio=0.0 if present else 100.0,
        ))

    for column in config.get("non_null_columns", []):
        if column not in frame.columns:
            rules.append(build_result(
                "non_null_columns",
                "Non-null columns",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        missing = series.isna() | series.map(lambda value: isinstance(value, str) and value.strip() == "")
        count = int(missing.sum())
        failed = count > 0
        rules.append(build_result(
            "non_null_columns",
            "Non-null columns",
            "FAIL" if failed else "PASS",
            "ERROR" if failed else "INFO",
            f"Column '{column}' has {count} missing values.",
            column=column,
            checked_count=int(len(series)),
            failed_count=count,
            examples=list(series[missing].index.tolist()[:5]),
            failure_ratio=round((count / len(series)) * 100, 2) if len(series) else 0.0,
        ))

    for column in config.get("unique_columns", []):
        if column not in frame.columns:
            rules.append(build_result(
                "unique_columns",
                "Unique columns",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        non_null = series[series.notna() & ~series.map(lambda value: isinstance(value, str) and value.strip() == "")]
        duplicate_mask = non_null.duplicated(keep="first")
        duplicate_count = int(duplicate_mask.sum())
        failed = duplicate_count > 0
        rules.append(build_result(
            "unique_columns",
            "Unique columns",
            "FAIL" if failed else "PASS",
            "ERROR" if failed else "INFO",
            f"Column '{column}' has {duplicate_count} duplicate non-null values.",
            column=column,
            checked_count=int(len(non_null)),
            failed_count=duplicate_count,
            examples=list(non_null[duplicate_mask].index.tolist()[:5]),
            failure_ratio=round((duplicate_count / len(non_null)) * 100, 2) if len(non_null) else 0.0,
        ))

    for column, allowed in config.get("allowed_values", {}).items():
        if column not in frame.columns:
            rules.append(build_result(
                "allowed_values",
                "Allowed values",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        allowed_set = {str(item) for item in allowed}
        valid_mask = series.notna() & ~series.map(lambda value: isinstance(value, str) and value.strip() == "")
        invalid = series[valid_mask & ~series.map(lambda value: str(value) in allowed_set)]
        failed_count = int(len(invalid))
        rules.append(build_result(
            "allowed_values",
            "Allowed values",
            "FAIL" if failed_count else "PASS",
            "ERROR" if failed_count else "INFO",
            f"Column '{column}' has {failed_count} values outside the allowed set.",
            column=column,
            checked_count=int(valid_mask.sum()),
            failed_count=failed_count,
            examples=list(invalid.index.tolist()[:5]),
            failure_ratio=round((failed_count / valid_mask.sum()) * 100, 2) if valid_mask.sum() else 0.0,
        ))

    for column, range_map in config.get("numeric_ranges", {}).items():
        if column not in frame.columns:
            rules.append(build_result(
                "numeric_ranges",
                "Numeric ranges",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        numeric = pd.to_numeric(series, errors="coerce")
        valid_mask = numeric.notna()
        lower = range_map["min"]
        upper = range_map["max"]
        bad = numeric[valid_mask & ((numeric < lower) | (numeric > upper))]
        failed_count = int(len(bad))
        rules.append(build_result(
            "numeric_ranges",
            "Numeric ranges",
            "FAIL" if failed_count else "PASS",
            "ERROR" if failed_count else "INFO",
            f"Column '{column}' has {failed_count} values outside [{lower}, {upper}].",
            column=column,
            checked_count=int(valid_mask.sum()),
            failed_count=failed_count,
            examples=list(bad.index.tolist()[:5]),
            failure_ratio=round((failed_count / valid_mask.sum()) * 100, 2) if valid_mask.sum() else 0.0,
        ))

    for column, expected_list in config.get("expected_types", {}).items():
        if column not in frame.columns:
            rules.append(build_result(
                "expected_types",
                "Expected types",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        bad_indexes: list[int] = []
        for idx, value in series.items():
            if pd.isna(value):
                continue
            matches = False
            for expected in expected_list:
                if expected in {"string", "str", "text"}:
                    matches = isinstance(value, str)
                elif expected in {"numeric", "number", "float", "int"}:
                    numeric_value = pd.to_numeric(str(value), errors="coerce")
                    matches = pd.notna(numeric_value)
                elif expected == "boolean":
                    matches = str(value).lower() in {"true", "false", "yes", "no", "1", "0"}
                if matches:
                    break
            if not matches:
                bad_indexes.append(int(idx))
        failed_count = len(bad_indexes)
        rules.append(build_result(
            "expected_types",
            "Expected types",
            "FAIL" if failed_count else "PASS",
            "ERROR" if failed_count else "INFO",
            f"Column '{column}' has {failed_count} values not matching expected types {expected_list}.",
            column=column,
            checked_count=len(series),
            failed_count=failed_count,
            examples=bad_indexes[:5],
            failure_ratio=round((failed_count / len(series)) * 100, 2) if len(series) else 0.0,
        ))

    for column, pattern in config.get("regex_patterns", {}).items():
        if column not in frame.columns:
            rules.append(build_result(
                "regex_patterns",
                "Regex patterns",
                "FAIL",
                "ERROR",
                f"Configured column '{column}' is missing.",
                column=column,
                checked_count=1,
                failed_count=1,
                examples=[],
                failure_ratio=100.0,
            ))
            continue
        regex = re.compile(pattern)
        series = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)
        invalid_indexes = [int(idx) for idx, value in series.items() if pd.notna(value) and str(value).strip() != "" and not regex.fullmatch(str(value))]
        failed_count = len(invalid_indexes)
        rules.append(build_result(
            "regex_patterns",
            "Regex patterns",
            "FAIL" if failed_count else "PASS",
            "ERROR" if failed_count else "INFO",
            f"Column '{column}' has {failed_count} values that do not match the regex.",
            column=column,
            checked_count=len(series),
            failed_count=failed_count,
            examples=invalid_indexes[:5],
            failure_ratio=round((failed_count / len(series)) * 100, 2) if len(series) else 0.0,
        ))

    duplicate_full_rows = int(frame.duplicated(keep="first").sum())
    policy = config.get("duplicate_row_policy", "warn")
    if policy == "ignore":
        row_status = "SKIP"
        row_severity = "INFO"
        row_message = "Duplicate-row validation is disabled by configuration."
    elif policy == "warn":
        row_status = "WARN" if duplicate_full_rows else "PASS"
        row_severity = "WARNING" if duplicate_full_rows else "INFO"
        row_message = f"Duplicate full rows found: {duplicate_full_rows}."
    else:
        row_status = "FAIL" if duplicate_full_rows else "PASS"
        row_severity = "ERROR" if duplicate_full_rows else "INFO"
        row_message = f"Duplicate full rows found: {duplicate_full_rows}."
    rules.append(build_result(
        "duplicate_rows",
        "Duplicate rows",
        row_status,
        row_severity,
        row_message,
        checked_count=len(frame),
        failed_count=duplicate_full_rows,
        examples=list(frame[frame.duplicated(keep="first")].index[:5].tolist()),
        failure_ratio=round((duplicate_full_rows / len(frame)) * 100, 2) if len(frame) else 0.0,
    ))

    return rules
