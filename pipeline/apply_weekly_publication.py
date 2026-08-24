#!/usr/bin/env python3
"""Attach one frozen weekly-feedback publication manifest to its Base record."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sync_weekly_feedback_base import rows_from_matrix


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


def validate_publication(record: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if record.get("反馈唯一键") != manifest.get("反馈唯一键"):
        raise RuntimeError("publication_feedback_key_mismatch")
    state = set(record.get("反馈状态") or [])
    if "已发布" in state:
        raise RuntimeError("feedback_already_published")
    if "已确认" not in state:
        raise RuntimeError("feedback_not_confirmed")
    fields = manifest.get("publication_fields")
    required = ("发布版本", "发布时间", "网页链接", "PDF链接")
    if not isinstance(fields, dict) or any(not fields.get(field) for field in required):
        raise RuntimeError("publication_manifest_incomplete")
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True, help="weekly_feedback_snapshot.json")
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", default="tbl0RnEoWpyPZ1ve")
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="bot")
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    snapshot = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = snapshot.get("manifest", snapshot)
    command = ["lark-cli", "base", "+record-get", "--base-token", args.base_token, "--table-id", args.table_id, "--record-id", args.record_id, "--as", args.identity, "--format", "json"]
    if args.profile:
        command += ["--profile", args.profile]
    records = rows_from_matrix(run_cli(command))
    if len(records) != 1:
        raise RuntimeError("weekly_feedback_record_not_found")
    fields = validate_publication(records[0], manifest)
    if not args.apply:
        print(json.dumps({"dry_run": True, "record_id": args.record_id, "fields": fields}, ensure_ascii=False, indent=2))
        return 0
    command = ["lark-cli", "base", "+record-upsert", "--base-token", args.base_token, "--table-id", args.table_id, "--record-id", args.record_id, "--json", json.dumps(fields, ensure_ascii=False), "--as", args.identity]
    if args.profile:
        command += ["--profile", args.profile]
    run_cli(command)
    print(json.dumps({"dry_run": False, "record_id": args.record_id, "version": fields["发布版本"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
