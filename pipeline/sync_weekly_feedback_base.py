#!/usr/bin/env python3
"""Safely create or update a pre-review 学生周反馈 Base record.

The command is dry-run by default.  It only writes a draft when an existing
row is still ``草稿``; ``已确认`` and ``已发布`` records are immutable here and
must be revised through the explicit publication flow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from student_ops.weekly_feedback_base import build_weekly_feedback_fields


def run_cli(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("lark_cli_invalid_response") from None
    if completed.returncode or not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "lark_cli_failed"))
    return response


def rows_from_matrix(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response["data"]
    fields = data["fields"]
    return [
        {"record_id": record_id, **dict(zip(fields, row))}
        for record_id, row in zip(data["record_id_list"], data["data"])
    ]


def find_feedback_record(base_token: str, table_id: str, unique_key: str, identity: str, profile: str | None) -> list[dict[str, Any]]:
    command = [
        "lark-cli", "base", "+record-list", "--base-token", base_token, "--table-id", table_id,
        "--field-id", "反馈唯一键", "--field-id", "学生学期", "--field-id", "反馈状态",
        "--filter-json", json.dumps({"logic": "and", "conditions": [["反馈唯一键", "==", unique_key]]}, ensure_ascii=False),
        "--limit", "10", "--as", identity, "--format", "json",
    ]
    if profile:
        command += ["--profile", profile]
    return rows_from_matrix(run_cli(command))


def load_result(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    return result["weekly_payload"]["payload"], result["weekly_drafts"], dict(raw.get("run_metadata") or {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True, help="run_student_ops 输出的 all_result.json")
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", default="tbl0RnEoWpyPZ1ve")
    parser.add_argument("--student-term-record-id", required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="bot")
    parser.add_argument("--profile")
    parser.add_argument("--allow-nonlive-artifact", action="store_true", help="local fixture/demo only; never use for real Base data")
    parser.add_argument("--apply", action="store_true", help="omit to print the exact safe write plan only")
    args = parser.parse_args()

    payload, drafts, metadata = load_result(args.result)
    if metadata.get("ai_mode") != "live" and not args.allow_nonlive_artifact:
        raise RuntimeError("non_live_ai_artifact")
    fields = build_weekly_feedback_fields(payload, drafts)
    matches = find_feedback_record(args.base_token, args.table_id, fields["反馈唯一键"], args.identity, args.profile)
    if len(matches) > 1:
        raise RuntimeError("duplicate_weekly_feedback_key")
    existing = matches[0] if matches else None
    if existing and existing.get("学生学期") != [{"id": args.student_term_record_id}]:
        raise RuntimeError("weekly_feedback_student_term_mismatch")
    if existing and set(existing.get("反馈状态") or []) & {"已确认", "已发布"}:
        raise RuntimeError("confirmed_or_published_feedback_is_immutable")
    if not existing:
        fields["学生学期"] = [{"id": args.student_term_record_id}]
    plan = {"operation": "update" if existing else "create", "record_id": existing and existing["record_id"], "fields": fields}
    if not args.apply:
        print(json.dumps({"dry_run": True, "plan": plan}, ensure_ascii=False, indent=2))
        return 0
    command = ["lark-cli", "base", "+record-upsert", "--base-token", args.base_token, "--table-id", args.table_id, "--json", json.dumps(fields, ensure_ascii=False), "--as", args.identity]
    if existing:
        command += ["--record-id", existing["record_id"]]
    if args.profile:
        command += ["--profile", args.profile]
    response = run_cli(command)
    print(json.dumps({"dry_run": False, "operation": plan["operation"], "record_id": response.get("data", {}).get("record", {}).get("record_id")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
