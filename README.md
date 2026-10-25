# DataSentry — Data Quality Checker

DataSentry is a small Python project that inspects CSV files for common data quality issues. It profiles the dataset, applies configurable business rules, stores results in SQLite, and exports JSON and HTML reports. The project is intentionally local, beginner-friendly, and easy to explain in an interview.

## Why this matters

Bad data creates broken dashboards, incorrect reports, and unreliable decisions. Data quality checks help catch missing values, duplicates, impossible ranges, invalid types, and malformed records before they spread downstream.

## Features

- CSV validation and file checks
- Row and column profiling
- Configurable rule engine using JSON
- Quality score calculation from 0 to 100
- SQLite history for runs and checks
- JSON and offline HTML reports
- Python CLI with `check`, `history`, and `show-run` commands

## Tech stack

- Python 3.10+
- pandas
- SQLite via Python standard library `sqlite3`
- argparse for CLI
- pytest for tests

## Architecture

```text
CSV input -> load + validate -> profile -> rules -> quality score -> SQLite + JSON/HTML reports
```

## Project tree

```text
DataSentry/
├── config/
│   └── example_rules.json
├── data/
│   ├── sample_customers.csv
│   └── sample_orders.csv
├── datasentry/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── csv_loader.py
│   ├── database.py
│   ├── exceptions.py
│   ├── orchestration.py
│   ├── profiling.py
│   ├── reporting.py
│   ├── rules.py
│   └── utils.py
├── reports/
│   └── .gitkeep
├── tests/
│   └── test_datasentry.py
├── .gitignore
├── README.md
├── dashboard.py
├── pyproject.toml
└── requirements.txt
```

**Note:** The SQLite database and generated reports are created locally and are not committed to the repository.

## Setup

### Windows PowerShell

```powershell
cd "C:\Users\abhay\OneDrive\Desktop\DataSentry"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS/Linux

```bash
cd ~/DataSentry
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Running the sample workflow

From the project root:

```bash
python -m datasentry check data/sample_customers.csv --config config/example_rules.json --database data/datasentry.db --reports-dir reports
```

This command prints a concise summary, the run ID, and the JSON/HTML report paths.

## Dashboard

Launch the interactive dashboard with:

```bash
streamlit run dashboard.py
```

The dashboard reads the project SQLite database, shows summary metrics, charts, recent runs, and drill-down details, and refreshes from the latest database state without reloading the app on its own.

## Custom configuration

```bash
python -m datasentry check data/sample_customers.csv --config config/example_rules.json --database data/datasentry.db --reports-dir reports
```

## History and run inspection

```bash
python -m datasentry history --database data/datasentry.db --limit 10
python -m datasentry show-run <run_id> --database data/datasentry.db
```

## Rule configuration

`config/example_rules.json` supports:

- `schema_version`: required value `1`
- `required_columns`: list of required columns
- `non_null_columns`: columns where empty values fail
- `unique_columns`: columns that must have no duplicates among non-empty values
- `allowed_values`: mapping of column to allowed values
- `numeric_ranges`: inclusive bounds with `min` and `max`
- `expected_types`: supported values such as `numeric`, `string`, `boolean`
- `regex_patterns`: regex string patterns
- `minimum_rows`: minimum acceptable row count
- `maximum_rows`: maximum acceptable row count
- `duplicate_row_policy`: `ignore`, `warn`, or `error`

Whitespace-only strings count as missing. Numeric boundaries are inclusive. Invalid numeric values are ignored when checking ranges unless they are blank; the rule counts only valid numeric entries. Regex validation is applied to non-empty values only.

## Quality score

The score is computed as:

```text
score = 100 * (passed + 0.5 * warned) / applicable_checks
```

Warnings count as half-credit. `SKIP` checks are excluded from the denominator. If no checks apply, the score is `null` rather than a misleading `100`.

## SQLite schema

DataSentry stores:

- `runs`: metadata about each analysis run
- `check_results`: one row per check result linked by foreign key to the run

## Reports

Each run writes:

- JSON summary with profile information and checks
- HTML report that is fully offline and escapes user data before rendering

## Exit codes

- `0`: success and no ERROR-severity check failed
- `1`: invalid input, configuration problem, persistence failure, or failed run
- `2`: CLI argument misuse

## Common errors and fixes

- Missing file: confirm the CSV path is correct and the file exists.
- Malformed CSV: inspect delimiters and quoting; the default is comma-separated and UTF-8.
- Invalid config: fix JSON syntax or rule types before rerunning.
- Unwritable database or report directory: check folder permissions.

## Limitations

This project is intentionally local and processes CSV files in memory. It does not support cloud storage, a web app, or distributed processing.

## Interview talking points

- Built a data quality checker from CSV ingestion through report output.
- Used Python and SQLite for a complete local workflow without external services.
- Implemented validation, profiling, metadata persistence, and transparent scoring.

Likely interview questions:

1. Why is data quality important?
   - Data quality issues can cause poor decisions and unreliable analytics.
2. What part of this project is most valuable?
   - The combination of business rules, measurable scoring, and historical storage makes the workflow trustworthy.
3. How would you extend it?
   - Add more rules, larger datasets, or richer output formats while keeping the core logic simple.

## License

This project is provided for educational use and does not require a commercial license.
