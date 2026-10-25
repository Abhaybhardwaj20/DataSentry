from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .exceptions import DataValidationError
from .utils import file_fingerprint


def load_csv(path: str | Path, delimiter: str = ",", encoding: str = "utf-8") -> tuple[pd.DataFrame, str]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise DataValidationError(f"CSV file does not exist: {csv_path}")
    if not csv_path.is_file():
        raise DataValidationError(f"Path is not a CSV file: {csv_path}")
    if csv_path.stat().st_size == 0:
        raise DataValidationError(f"CSV file is empty: {csv_path}")

    try:
        with csv_path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            header = next(reader)
    except UnicodeDecodeError as exc:
        raise DataValidationError(f"Unable to decode CSV with encoding '{encoding}': {csv_path}. {exc}") from exc
    except csv.Error as exc:
        raise DataValidationError(f"Malformed CSV file: {csv_path}. {exc}") from exc
    except OSError as exc:
        raise DataValidationError(f"Could not read CSV: {csv_path}. {exc}") from exc

    if not header:
        raise DataValidationError(f"CSV file has no header row: {csv_path}")
    if any(str(name).strip() == "" for name in header):
        raise DataValidationError("CSV contains a blank column name.")
    if len(header) != len(set(header)):
        raise DataValidationError("CSV contains duplicate column names. Rename the columns to be unique.")

    try:
        frame = pd.read_csv(
            csv_path,
            delimiter=delimiter,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
            na_values=["", "NA", "N/A", "null", "NULL"],
            on_bad_lines="error",
        )
    except UnicodeDecodeError as exc:
        raise DataValidationError(f"Unable to decode CSV with encoding '{encoding}': {csv_path}. {exc}") from exc
    except pd.errors.ParserError as exc:
        raise DataValidationError(f"Malformed CSV file: {csv_path}. {exc}") from exc
    except ValueError as exc:
        raise DataValidationError(f"Malformed CSV file: {csv_path}. {exc}") from exc
    except Exception as exc:
        raise DataValidationError(f"Could not load CSV: {csv_path}. {exc}") from exc

    return frame, file_fingerprint(csv_path)
