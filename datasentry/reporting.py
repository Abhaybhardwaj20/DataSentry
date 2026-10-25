from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .utils import ensure_parent_dir, html_escape, json_dumps, safe_filename


def write_json_report(payload: dict[str, Any], reports_dir: str | Path) -> str:
    target_dir = ensure_parent_dir(reports_dir)
    run_id = str(payload["run_id"])
    path = target_dir / f"{safe_filename(run_id)}.json"
    payload = json.loads(json_dumps(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def write_html_report(payload: dict[str, Any], reports_dir: str | Path) -> str:
    target_dir = ensure_parent_dir(reports_dir)
    run_id = str(payload["run_id"])
    path = target_dir / f"{safe_filename(run_id)}.html"
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = ""
    for profile in payload.get("profile", {}).get("column_profiles", []):
        stats = profile["stats"]
        rows += "<tr>"
        rows += f"<td>{escape(profile['column'])}</td>"
        rows += f"<td>{escape(str(stats.get('inferred_type')))}</td>"
        rows += f"<td>{escape(str(stats.get('missing_count')))}</td>"
        rows += f"<td>{escape(str(stats.get('missing_percentage')))}</td>"
        rows += f"<td>{escape(str(stats.get('distinct_non_null_count')))}</td>"
        rows += f"<td>{escape(str(stats.get('min')))}</td>"
        rows += f"<td>{escape(str(stats.get('max')))}</td>"
        rows += f"<td>{escape(str(stats.get('mean')))}</td>"
        rows += f"<td>{escape(str(stats.get('median')))}</td>"
        rows += "</tr>"

    check_rows = ""
    for check in payload.get("checks", []):
        check_rows += "<tr>"
        check_rows += f"<td>{escape(check.get('check_id',''))}</td>"
        check_rows += f"<td>{escape(check.get('name',''))}</td>"
        check_rows += f"<td>{escape(check.get('status',''))}</td>"
        check_rows += f"<td>{escape(check.get('severity',''))}</td>"
        check_rows += f"<td>{escape(str(check.get('column','')))}</td>"
        check_rows += f"<td>{escape(str(check.get('failed_count','')))}</td>"
        check_rows += f"<td>{escape(check.get('message',''))}</td>"
        check_rows += f"<td>{escape(str(check.get('example_row_numbers',[])))} </td>"
        check_rows += "</tr>"

    html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
    <head>
      <meta charset=\"utf-8\">
      <title>DataSentry Report</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; color: #1f2937; }}
        .summary {{ margin-bottom: 2rem; border-bottom: 1px solid #e5e7eb; padding-bottom: 1rem; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
        th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; vertical-align: top; }}
        th {{ background: #f3f4f6; }}
      </style>
    </head>
    <body>
      <h1>DataSentry Quality Report</h1>
      <div class=\"summary\">
        <p><strong>Run ID:</strong> {escape(str(payload.get('run_id','')))}</p>
        <p><strong>Timestamp:</strong> {escape(str(payload.get('timestamp','')))}</p>
        <p><strong>Source:</strong> {escape(str(payload.get('source_name','')))}</p>
        <p><strong>Rows:</strong> {escape(str(payload.get('row_count','')))} | <strong>Columns:</strong> {escape(str(payload.get('column_count','')))}</p>
        <p><strong>Score:</strong> {escape(str(payload.get('score','')))} | <strong>Status:</strong> {escape(str(payload.get('status','')))}</p>
      </div>

      <h2>Column profile</h2>
      <table>
        <thead>
          <tr>
            <th>Column</th><th>Type</th><th>Missing</th><th>Missing %</th><th>Distinct</th><th>Min</th><th>Max</th><th>Mean</th><th>Median</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <h2>Checks</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Name</th><th>Status</th><th>Severity</th><th>Column</th><th>Failed</th><th>Message</th><th>Examples</th>
          </tr>
        </thead>
        <tbody>{check_rows}</tbody>
      </table>
    </body>
    </html>
    """
    path.write_text(html, encoding="utf-8")
    return str(path)
