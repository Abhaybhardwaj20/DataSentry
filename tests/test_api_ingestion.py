from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from datasentry.api_ingestion import fetch_api_records, run_api_etl
from datasentry.exceptions import DataValidationError


@patch("datasentry.api_ingestion.requests.get")
def test_fetch_api_records_success(mock_get):
    payload = {
        "products": [
            {"id": 1, "title": "Phone", "price": 999.99, "category": "electronics"},
            {"id": 2, "title": "Laptop", "price": 1499.50, "category": "electronics"},
        ]
    }
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    df = fetch_api_records("https://example.com/products", timeout=10)

    assert list(df.columns) == ["id", "title", "price", "category"]
    assert len(df) == 2
    assert df.iloc[0]["title"] == "Phone"


@patch("datasentry.api_ingestion.requests.get")
def test_fetch_api_records_empty_response_raises(mock_get):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"products": []}
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    with pytest.raises(DataValidationError, match="empty"):
        fetch_api_records("https://example.com/products")


@patch("datasentry.api_ingestion.requests.get")
def test_fetch_api_records_malformed_response_raises(mock_get):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"meta": {"count": 2}}
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    with pytest.raises(DataValidationError, match="records"):
        fetch_api_records("https://example.com/products")


@patch("datasentry.api_ingestion.requests.get")
def test_fetch_api_records_http_error_raises(mock_get):
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = requests.HTTPError("API outage")
    mock_get.return_value = mock_response

    with pytest.raises(DataValidationError, match="HTTP 500|Failed to fetch"):
        fetch_api_records("https://example.com/products")


@patch("datasentry.api_ingestion.requests.get")
def test_fetch_api_records_timeout_raises(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")

    with pytest.raises(DataValidationError, match="timed out|timeout"):
        fetch_api_records("https://example.com/products")


@patch("datasentry.api_ingestion.fetch_api_records")
def test_run_api_etl_uses_existing_pipeline(mock_fetch, tmp_path):
    frame = pd.DataFrame(
        [
            {"order_id": "API-1", "customer_name": "Alice", "email": "alice@example.com", "order_date": "2026-03-01", "product": "Phone", "quantity": 2, "unit_price": 99, "status": "Completed", "city": "Delhi"},
            {"order_id": "API-2", "customer_name": "Bob", "email": "bob@example.com", "order_date": "2026-03-02", "product": "Monitor", "quantity": 1, "unit_price": 199, "status": "Pending", "city": "Jaipur"},
        ]
    )
    mock_fetch.return_value = frame

    db_path = tmp_path / "api_history.db"
    output_root = tmp_path / "api_layers"

    result = run_api_etl("https://example.com/api/orders", database_path=db_path, output_root=output_root)

    assert result["status"] in {"SUCCESS", "WARN"}
    assert result["input_rows"] == 2
    assert Path(result["raw_path"]).exists()
    assert Path(result["silver_path"]).exists()
    assert Path(result["gold_path"]).exists()
