from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from datasentry.database import DataSentryDatabase
from datasentry.dashboard import load_dashboard_data


st.set_page_config(page_title="DataSentry Dashboard", layout="wide")


def _error_box(message: str) -> None:
    st.warning(message)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@st.cache_data(show_spinner=False)
def load_dashboard_snapshot(db_path: str) -> dict[str, Any]:
    return load_dashboard_data(db_path)


# Main app
if __name__ == "__main__":
    db_path = st.text_input("SQLite database path", value="data/datasentry.db")
    refresh = st.button("Refresh data")

    if refresh or True:
        try:
            snapshot = load_dashboard_snapshot(db_path)
        except Exception as exc:  # pragma: no cover
            _error_box(f"Could not load data: {exc}")
            st.stop()

        summary = snapshot.get("summary", {})
        history = snapshot.get("history", [])
        breakdown = snapshot.get("breakdown", [])

        if not history:
            st.title("DataSentry Dashboard")
            st.info("No runs yet. Run a check from the CLI to populate the database.")
            st.stop()

        runs_df = pd.DataFrame(history)
        if "created_at" in runs_df.columns:
            runs_df["created_at"] = pd.to_datetime(runs_df["created_at"], errors="coerce")
        runs_df = runs_df.sort_values("created_at", ascending=True, na_position="last") if "created_at" in runs_df.columns else runs_df

        st.title("DataSentry Dashboard")

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total runs", summary.get("total_runs", 0))
        col2.metric("Latest score", summary.get("latest_score", 0.0))
        col3.metric("Latest status", summary.get("latest_status", "UNKNOWN"))
        col4.metric("Latest violations", summary.get("total_violations", 0))
        col5.metric("Pass / fail", f"{summary.get('pass_count', 0)} / {summary.get('fail_count', 0)}")

        if runs_df.empty:
            st.info("No runs available for charting.")
            st.stop()

        score_fig = px.line(
            runs_df,
            x="created_at" if "created_at" in runs_df.columns else runs_df.index,
            y="score" if "score" in runs_df.columns else None,
            markers=True,
            title="Quality score across runs",
            labels={"created_at": "Timestamp", "score": "Quality score"},
        )
        st.plotly_chart(score_fig, use_container_width=True)

        if breakdown:
            breakdown_df = pd.DataFrame(breakdown)
            breakdown_fig = px.bar(
                breakdown_df,
                x="check_id",
                y="total_failures",
                title="Violation counts by rule",
                labels={"check_id": "Rule", "total_failures": "Failures"},
            )
            st.plotly_chart(breakdown_fig, use_container_width=True)

        status_counts = snapshot.get("status_counts", {})
        if status_counts:
            status_df = pd.DataFrame([{"status": k, "count": v} for k, v in status_counts.items()])
            pass_fail_fig = px.bar(status_df, x="status", y="count", title="Pass/fail run counts")
            st.plotly_chart(pass_fail_fig, use_container_width=True)

        st.subheader("Recent runs")
        st.dataframe(runs_df, use_container_width=True)

        selected_run = st.selectbox("Select run to inspect", options=[str(run["id"]) for run in history], index=0)
        run_details = DataSentryDatabase(db_path).get_run(selected_run)
        if run_details:
            st.subheader(f"Run details: {selected_run}")
            st.json({k: v for k, v in run_details.items() if k != "checks"})
            st.dataframe(pd.DataFrame(run_details.get("checks", [])))
        else:
            st.warning("Selected run was not found in the database.")
