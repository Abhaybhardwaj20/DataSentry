import pandas as pd
from pathlib import Path

from datasentry.cli import main
from datasentry.pipeline import _build_gold_layer, _validate_rows, run_etl_pipeline


def test_pipeline_creates_raw_bronze_silver_and_gold_layers(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "order_id,customer_name,email,order_date,product,quantity,unit_price,status,city\n"
        "ORD0001,Alice,alice@example.com,2026-02-03,Phone,2,99,Completed,Delhi\n"
        "ORD0001,Alice,alice@example.com,2026-02-03,Phone,2,99,Completed,Delhi\n"
        "ORD0002,,bob@example.com,2026/02/04,Monitor,0,199,Completed,Delhi\n"
        "ORD0003,Bob,bad-email,2026-02-05,Mouse,3,55,Unknown,Chandigarh\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "etl.db"
    output_root = tmp_path / "layers"

    result = run_etl_pipeline(
        source_path=source,
        database_path=db_path,
        output_root=output_root,
    )

    assert result["run_id"]
    assert Path(result["raw_path"]).exists()
    assert Path(result["bronze_path"]).exists()
    assert Path(result["silver_path"]).exists()
    assert Path(result["gold_path"]).exists()
    assert result["input_rows"] == 4
    assert result["valid_rows"] >= 1
    assert result["rejected_rows"] >= 1
    assert result["status"] in {"SUCCESS", "WARN"}

    gold = pd.read_csv(result["gold_path"])
    overall = gold.loc[gold["aggregation"] == "overall"].iloc[0]
    assert overall["total_valid_orders"] == 1
    assert overall["total_sales_revenue"] == 198


def test_gold_layer_calculates_overall_and_dimension_metrics():
    valid_rows = pd.DataFrame(
        [
            {"order_id": "A", "product": "Phone", "quantity": 2, "unit_price": 10, "order_date": "2026-01-01", "city": "Delhi", "status": "Completed"},
            {"order_id": "B", "product": "Phone", "quantity": 1, "unit_price": 20, "order_date": "2026-01-01", "city": "Delhi", "status": "Completed"},
            {"order_id": "C", "product": "Mouse", "quantity": 3, "unit_price": 5, "order_date": "2026-01-02", "city": "Mumbai", "status": "Pending"},
            {"order_id": "A", "product": "Mouse", "quantity": 100, "unit_price": 100, "order_date": "2026-01-03", "city": "Pune", "status": "Cancelled"},
        ]
    )

    gold = _build_gold_layer(valid_rows)

    overall = gold.loc[gold["aggregation"] == "overall"].iloc[0]
    assert overall["total_valid_orders"] == 3
    assert overall["total_sales_revenue"] == 55
    assert overall["average_order_value"] == 55 / 3

    phone = gold.loc[(gold["aggregation"] == "product") & (gold["product"] == "Phone")].iloc[0]
    assert phone["order_count"] == 2
    assert phone["gross_revenue"] == 40

    delhi = gold.loc[(gold["aggregation"] == "city") & (gold["city"] == "Delhi")].iloc[0]
    assert delhi["total_valid_orders"] == 2
    assert delhi["total_sales_revenue"] == 40

    completed = gold.loc[(gold["aggregation"] == "status") & (gold["status"] == "Completed")].iloc[0]
    assert completed["order_count"] == 2
    assert completed["gross_revenue"] == 40

    daily = gold.loc[(gold["aggregation"] == "daily") & (gold["order_date"] == "2026-01-01")].iloc[0]
    assert daily["total_valid_orders"] == 2
    assert daily["total_sales_revenue"] == 40

    city_status = gold.loc[
        (gold["aggregation"] == "city_status")
        & (gold["city"] == "Delhi")
        & (gold["status"] == "Completed")
    ].iloc[0]
    assert city_status["order_count"] == 2
    assert city_status["gross_revenue"] == 40


def test_gold_layer_empty_input_keeps_metric_columns():
    empty = pd.DataFrame(columns=["order_id", "product", "quantity", "unit_price", "order_date", "city", "status"])

    gold = _build_gold_layer(empty)

    assert gold.empty
    assert "total_valid_orders" in gold.columns
    assert "total_sales_revenue" in gold.columns


def test_validation_rejects_invalid_and_duplicate_order_ids():
    frame = pd.DataFrame({"order_id": ["", "A", "A", "B"]})
    config = {
        "required_columns": ["order_id"],
        "non_null_columns": ["order_id"],
        "unique_columns": ["order_id"],
        "duplicate_row_policy": "ignore",
    }

    valid, rejected = _validate_rows(frame, config)

    assert valid["order_id"].tolist() == ["A", "B"]
    assert len(rejected) == 2


def test_cli_pipeline_runs_successfully(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text(
        "order_id,customer_name,email,order_date,product,quantity,unit_price,status,city\n"
        "A-1,Charlie,charlie@example.com,2026-03-01,Keyboard,4,299,Completed,Delhi\n"
        "A-2,Donna,donna@example.com,2026-03-02,Monitor,2,499,Pending,Jaipur\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "history.db"
    output_root = tmp_path / "curated"

    rc = main(["etl", str(source), "--database", str(db_path), "--output-root", str(output_root)])
    assert rc == 0
