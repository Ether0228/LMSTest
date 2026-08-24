#!/usr/bin/env python3
"""Render a non-public teacher preview from workflow facts plus current Base drafts."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from student_ops.publishing import render_pdf, render_weekly_html
from student_ops.weekly_feedback_drafts import TEXT_FIELDS, apply_feedback_record
from sync_weekly_feedback_base import rows_from_matrix


def run_cli(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    response = json.loads(raw)
    if completed.returncode or not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "lark_cli_failed"))
    return response


def read_feedback_record(*, base_token: str, table_id: str, record_id: str, identity: str, profile: str | None) -> dict[str, Any]:
    command = ["lark-cli", "base", "+record-get", "--base-token", base_token, "--table-id", table_id, "--record-id", record_id, "--as", identity, "--format", "json"]
    if profile:
        command.extend(("--profile", profile))
    rows = rows_from_matrix(run_cli(command))
    if len(rows) != 1:
        raise RuntimeError("weekly_feedback_record_not_found")
    return rows[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True, help="all_result.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-token")
    parser.add_argument("--table-id", default="tbl0RnEoWpyPZ1ve")
    parser.add_argument("--feedback-record-id")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    if bool(args.base_token) != bool(args.feedback_record_id):
        raise ValueError("base_token_and_feedback_record_id_must_be_used_together")
    raw = json.loads(args.result.read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    payload = result["weekly_payload"]["payload"]
    generated = result["weekly_drafts"]["payload"]["drafts"]
    record = read_feedback_record(base_token=args.base_token, table_id=args.table_id, record_id=args.feedback_record_id, identity=args.identity, profile=args.profile) if args.base_token else {}
    if record and record.get("反馈唯一键") != payload.get("反馈唯一键"):
        raise RuntimeError("preview_feedback_key_mismatch")
    effective_payload, drafts = apply_feedback_record(payload, generated, record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    html = render_weekly_html(effective_payload, drafts)
    html_path, pdf_path = args.output_dir / "weekly_feedback_preview.html", args.output_dir / "weekly_feedback_preview.pdf"
    html_path.write_text(html, encoding="utf-8")
    render_pdf(html_path, pdf_path)
    snapshot_path = args.output_dir / "weekly_feedback_preview_snapshot.json"
    snapshot_path.write_text(json.dumps({"payload": effective_payload, "drafts": drafts, "base_record_id": record.get("record_id") if record else None, "editable_fields": list(TEXT_FIELDS)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"preview": str(html_path), "pdf": str(pdf_path), "snapshot": str(snapshot_path), "source": "base_drafts" if record else "generated_drafts"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
