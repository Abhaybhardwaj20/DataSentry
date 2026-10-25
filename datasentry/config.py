from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .exceptions import ConfigError

VALID_KEYS = {
    "schema_version",
    "required_columns",
    "non_null_columns",
    "unique_columns",
    "allowed_values",
    "numeric_ranges",
    "expected_types",
    "regex_patterns",
    "minimum_rows",
    "maximum_rows",
    "duplicate_row_policy",
}


def load_rules(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Configuration file does not exist: {config_path}")
    if not config_path.is_file():
        raise ConfigError(f"Configuration path is not a file: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Malformed JSON configuration: {config_path}. {exc.msg} at line {exc.lineno} column {exc.colno}.") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file: {config_path}. {exc}") from exc

    validate_rules(data)
    return data


def validate_rules(config: Any) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Configuration must be a JSON object.")

    unknown_keys = sorted(set(config) - VALID_KEYS)
    if unknown_keys:
        raise ConfigError(f"Unknown configuration keys are not allowed: {', '.join(unknown_keys)}")

    if "schema_version" not in config:
        raise ConfigError("Missing required schema_version value.")
    if config["schema_version"] != 1:
        raise ConfigError("Unsupported schema_version. Only schema_version 1 is supported.")

    for key in ["required_columns", "non_null_columns", "unique_columns"]:
        if key in config:
            value = config[key]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ConfigError(f"'{key}' must be a list of column names.")

    if "allowed_values" in config:
        value = config["allowed_values"]
        if not isinstance(value, dict):
            raise ConfigError("'allowed_values' must be an object mapping columns to allowed values.")
        for column, allowed in value.items():
            if not isinstance(column, str):
                raise ConfigError("Allowed values keys must be column names.")
            if not isinstance(allowed, list):
                raise ConfigError(f"Allowed values for '{column}' must be a list.")

    if "numeric_ranges" in config:
        value = config["numeric_ranges"]
        if not isinstance(value, dict):
            raise ConfigError("'numeric_ranges' must be an object mapping columns to range objects.")
        for column, range_map in value.items():
            if not isinstance(column, str):
                raise ConfigError("Numeric range keys must be column names.")
            if not isinstance(range_map, dict):
                raise ConfigError(f"Range for '{column}' must be an object with min and max values.")
            if set(range_map) - {"min", "max"}:
                raise ConfigError(f"Range for '{column}' must contain only 'min' and 'max'.")
            if "min" not in range_map or "max" not in range_map:
                raise ConfigError(f"Range for '{column}' must include both 'min' and 'max'.")
            if not isinstance(range_map["min"], (int, float)) or not isinstance(range_map["max"], (int, float)):
                raise ConfigError(f"Range limits for '{column}' must be numeric.")

    if "expected_types" in config:
        value = config["expected_types"]
        if not isinstance(value, dict):
            raise ConfigError("'expected_types' must be an object mapping columns to type names.")
        for column, expected in value.items():
            if not isinstance(column, str):
                raise ConfigError("Expected type keys must be column names.")
            if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
                raise ConfigError(f"Expected type list for '{column}' must be a list of strings.")

    if "regex_patterns" in config:
        value = config["regex_patterns"]
        if not isinstance(value, dict):
            raise ConfigError("'regex_patterns' must be an object mapping columns to regex strings.")
        for column, pattern in value.items():
            if not isinstance(column, str):
                raise ConfigError("Regex keys must be column names.")
            if not isinstance(pattern, str):
                raise ConfigError(f"Regex pattern for '{column}' must be a string.")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"Invalid regular expression for '{column}': {pattern}. {exc}") from exc

    for key in ["minimum_rows", "maximum_rows"]:
        if key in config:
            value = config[key]
            if not isinstance(value, int) or value < 0:
                raise ConfigError(f"'{key}' must be a non-negative integer.")

    if "duplicate_row_policy" in config:
        value = config["duplicate_row_policy"]
        if value not in {"ignore", "warn", "error"}:
            raise ConfigError("'duplicate_row_policy' must be one of: ignore, warn, error.")
