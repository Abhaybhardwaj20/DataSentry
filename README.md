# DataSentry

DataSentry is a local Python data engineering project for CSV and public JSON API ETL workflows, data validation, and quality reporting. The repository combines a practical ETL pattern with a reusable rule engine so it can be used as a portfolio project for entry-level data engineering roles.

## Problem statement

Modern data teams need reliable ingestion, cleaning, validation, and reporting workflows. This project demonstrates a complete local pipeline that validates raw files, stores cleaned data in bronze/silver/gold layers, and records execution metadata in SQLite so the process remains explainable and repeatable.

## Objectives

- Ingest CSV files or public JSON APIs and validate required data and columns
- Standardize and transform source data without altering the original input
- Split the workflow into raw, bronze, silver, and gold layers
- Track run metadata, accepted rows, and rejected rows in SQLite
- Produce structured quality checks and offline reports
- Keep the project runnable locally without cloud credentials or paid services

## Architecture

```text
CSV or public API source
  -> raw layer (original file as extracted)
  -> bronze layer (normalized column names, trimmed strings)
  -> silver layer (valid cleaned rows, duplicates removed, rejected quarantined)
  -> gold layer (aggregated business-ready summary)
  -> SQLite metadata + JSON/HTML reports
```

## Technology stack

- Python 3.10+
- pandas
- SQLite via the stdlib `sqlite3` module
- argparse-based CLI
- pytest
- optional Streamlit dashboard for historical run review

## Directory structure

```text
DataSentry/
├── config/
│   ├── example_rules.json
│   ├── sales_rules.json
│   └── schedule.example.json
├── data/
│   ├── datasentry_sales_test_dataset.csv
│   ├── sample_customers.csv
│   ├── sample_orders.csv
│   └── etl_demo/
│       ├── raw/
│       ├── bronze/
│       ├── silver/
│       └── gold/
├── datasentry/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── csv_loader.py
│   ├── dashboard.py
│   ├── database.py
│   ├── exceptions.py
│   ├── orchestration.py
│   ├── pipeline.py
│   ├── profiling.py
│   ├── reporting.py
│   ├── rules.py
│   ├── scheduler.py
│   └── utils.py
├── reports/
├── tests/
│   ├── test_datasentry.py
│   ├── test_etl_pipeline.py
│   ├── test_api_ingestion.py
│   └── test_scheduler.py
├── dashboard.py
├── README.md
├── requirements.txt
├── pyproject.toml
├── .gitignore
└── data/datasentry.db
```

## Prerequisites

- Python 3.10+
- pip
- a local virtual environment is recommended

## Installation

```bash
cd "C:\Users\abhay\OneDrive\Desktop\DataSentry"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Dataset

The bundled sample dataset is `data/datasentry_sales_test_dataset.csv`. It models sales order records with columns such as `order_id`, `customer_name`, `email`, `order_date`, `product`, `quantity`, `unit_price`, `status`, and `city`.

## ETL workflow

The existing CSV ETL command is:

```bash
python -m datasentry etl data/datasentry_sales_test_dataset.csv --config config/sales_rules.json --database data/datasentry.db --output-root data/etl_demo
```

Public JSON API ingestion uses the same extraction-to-gold pipeline:

```bash
python -m datasentry api "https://dummyjson.com/products?limit=5" --database data/datasentry.db --output-root data/api_demo
```

The API command fetches a public, no-auth JSON response, normalizes the records into a dataframe, and sends them through the same bronze/silver/gold stages already used by the CSV workflow.

The same API workflow is also available through `etl --api-url`; the `api` command is the shorter form. Both ingestion paths reuse the existing ETL pipeline and validation rules.

What each layer does:

- Raw: preserves the original extracted CSV file exactly as it was received
- Bronze: trims spaces, normalizes column names, and standardizes values
- Silver: removes duplicates and rejects rows that violate required rules
- Gold: reports overall, product, city, status, daily, and legacy city/status sales summaries. Each aggregate includes valid order count, gross revenue, and average order value.

The ETL workflow is safe to rerun because each run writes a unique, timestamped output set and records a run ID in SQLite.

## Data quality rules

The bundled rule set covers:
- required columns
- missing values
- duplicate rows
- allowed values
- numeric range checks
- email format validation
- duplicate policy behavior (`warn` or `error`)

Rows that fail validation are not silently discarded. They are tracked in the ETL run result as rejected rows and can be reviewed from the output summary or the SQLite metadata table.

## Storage design

SQLite is used for lightweight local metadata storage:

- `runs`: core quality-checking execution history
- `check_results`: detailed rule results per run
- `pipeline_runs`: ETL execution summaries with run ID, timestamps, valid/rejected row counts, file paths, and status

The output layers are written as CSV files under the chosen output root directory so they remain inspectable without requiring a database client.

## CLI usage

### Data quality check

```bash
python -m datasentry check data/datasentry_sales_test_dataset.csv --config config/sales_rules.json --database data/datasentry.db --reports-dir reports
```

### ETL pipeline

```bash
python -m datasentry etl data/datasentry_sales_test_dataset.csv --config config/sales_rules.json --database data/datasentry.db --output-root data/etl_demo
python -m datasentry api "https://dummyjson.com/products?limit=5" --config config/sales_rules.json --database data/datasentry.db --output-root data/api_demo
```

### Automated scheduling

The scheduler is part of the existing Python package and requires no additional dependency or service. Start it with a JSON configuration:

```bash
python -m datasentry schedule --config config/schedule.example.json
```

The example schedules the bundled CSV dataset hourly. A run starts immediately, then repeats after the configured delay following completion. Executions are sequential, so scheduled runs do not overlap. Press `Ctrl+C` to request shutdown; DataSentry finishes the current ETL run before stopping. Do not close the terminal forcibly if the current run needs to finish.

Configuration uses `source_type` (`csv` or `api`), the matching `csv_path` or `api_url`, and a positive `interval_seconds`. Optional settings are `config_path`, `database`, `output_root`, `delimiter`, `encoding`, `timeout`, `dry_run`, and `log_file`. API schedules may also specify JSON objects for request `params` and `headers`. Paths are resolved from the current working directory. For an API schedule, set `source_type` to `api`, remove `csv_path`, and use settings such as:

```json
{
  "source_type": "api",
  "api_url": "https://dummyjson.com/products?limit=5",
  "interval_seconds": 3600,
  "config_path": "config/sales_rules.json",
  "database": "data/datasentry.db",
  "output_root": "data/scheduled_api",
  "timeout": 30,
  "params": {},
  "headers": {},
  "log_file": "logs/datasentry-scheduler.log"
}
```

Scheduled start times, completion status, run IDs, and errors are written to the console and configured log file. `WARN` results remain warnings; exceptions and unexpected ETL statuses are logged as failures, and later scheduled runs continue. Keep sensitive request headers out of committed configuration files.

### History and run inspection

```bash
python -m datasentry history --database data/datasentry.db --limit 10
python -m datasentry show-run <run_id> --database data/datasentry.db
```

### Dashboard

```bash
streamlit run dashboard.py
```

## Sample execution result

This project was executed against the bundled sales dataset using:

```bash
python -m datasentry etl data/datasentry_sales_test_dataset.csv --config config/sales_rules.json --database data/datasentry.db --output-root data/etl_demo
```

Actual result:

- Run ID: `5b36eec6-8241-4d44-85f0-08d8f15b7212`
- Status: `WARN`
- Input rows: `100`
- Valid rows: `89`
- Rejected rows: `11`

The Gold CSV identifies each row's grouping in `aggregation` (`overall`, `product`, `city`, `status`, `daily`, or `city_status`). It retains the original `city`, `status`, `order_count`, `gross_revenue`, and `average_order_value` columns; `total_valid_orders` and `total_sales_revenue` make the overall and dimensional metrics explicit. Average order value is revenue divided by distinct order IDs in that aggregate. Revenue is `quantity * unit_price` across all accepted statuses, including pending and cancelled orders; the status breakdown lets consumers separate those values.

For the bundled dataset and `config/sales_rules.json`, the verified Gold overall row has 88 valid orders, `total_sales_revenue` of 2,505,433, and `average_order_value` of about 28,470.83. The ETL reports 100 input rows, 88 valid rows, and 12 rejected rows (`WARN`).

Rows rejected by Silver validation never reach Gold. `order_id` is treated as a unique order key: after other validity checks, the first valid occurrence is kept and subsequent occurrences are rejected. Gold also defensively keeps one row per order ID. This assumes the sales input has one record per order rather than multiple line items per order.

## Logging and monitoring

Each ETL run stores:

- run ID
- source file name and fingerprint
- start and end timestamps
- duration in seconds
- input row count
- valid row count
- rejected row count
- run status
- output file paths
- error details when applicable

This is enough for a lightweight portfolio-ready execution history without introducing a distributed scheduler.

## API ingestion notes

The API ingestion path is intentionally simple and safe:

- it uses a public JSON API with no authentication
- it validates the HTTP response and JSON payload before processing
- it raises clear errors for timeouts, HTTP failures, and malformed payloads
- it converts API records into rows that can be processed by the existing ETL stages

The project does not implement cloud storage or distributed orchestration. The API path is local-first and designed for demonstration and learning.

## Test execution

Run the automated test suite with:

```bash
pytest -q
```

Scheduler tests mock ETL calls and use a fake stop event, so they neither wait for real intervals nor contact a public API.

## Troubleshooting

- Missing CSV file: verify the path is correct and the file exists
- Invalid config or missing columns: check the JSON schema and required field names
- Empty input: ensure the source contains data and a header row
- Rejected rows: inspect the ETL result summary or stored run details
- Write permission issues: ensure the output directory is writable

## Cloud scope

Cloud storage and cloud scheduling are intentionally out of scope. The scheduler runs in the local process and does not require cloud credentials.

## Current limitations

- ETL processing is local and file-based rather than distributed
- Scheduling is in-process and requires the machine and terminal session to remain running
- Schedules use a fixed delay after each run, not calendar or cron expressions
- Missed runs are not replayed after shutdown, and schedules are not persisted in the database
- API records are normalized to the existing sales-order schema, so unrelated API schemas may need source-specific mapping or rules

## Future improvements

- add more robust quarantine tables and row-level rejection reasons
- add incremental load support using watermark columns
- extend the gold layer with date-based trends and KPI dashboards

## License

This project is provided for educational and portfolio use and is intentionally lightweight and local-first.
