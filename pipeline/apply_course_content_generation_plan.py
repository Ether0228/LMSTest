#!/usr/bin/env python3
"""Apply reviewed AI course-content candidate plans without granting confirmation."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


ALLOWED_FIELDS = frozenset({"课程内容AI候选", "课程内容结构化结果", "内容生成状态", "内容生成异常", "内容Schema版本", "内容生成时间", "内容确认状态"})


def validate(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    updates = list(plan.get("session_updates") or [])
    if plan.get("exceptions"):
        raise RuntimeError("course_content_plan_contains_exceptions")
    for row in updates:
        if not row.get("record_id") or not isinstance(row.get("fields"), Mapping):
            raise RuntimeError("course_content_plan_invalid_update")
        if set(row["fields"]) - ALLOWED_FIELDS:
            raise RuntimeError("course_content_plan_contains_unapproved_fields")
        if row["fields"].get("内容确认状态") not in (None, ["待确认"]):
            raise RuntimeError("ai_candidate_must_not_confirm_content")
    return updates


def write(*, base_token: str, table_id: str, update: Mapping[str, Any], identity: str, profile: str | None) -> None:
    command = ["lark-cli", "base", "+record-upsert", "--base-token", base_token, "--table-id", table_id, "--record-id", str(update["record_id"]), "--json", json.dumps(update["fields"], ensure_ascii=False), "--as", identity]
    if profile:
        command.extend(("--profile", profile))
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError("lark_cli_failed")
    response = json.loads(completed.stdout)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "lark_cli_failed"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", default="tbllrHXPQrAcRfCR")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    updates = validate(json.loads(args.plan.read_text(encoding="utf-8")))
    if not args.apply:
        print(json.dumps({"dry_run": True, "updates": updates}, ensure_ascii=False, indent=2))
        return 0
    for update in updates:
        write(base_token=args.base_token, table_id=args.table_id, update=update, identity=args.identity, profile=args.profile)
    print(json.dumps({"dry_run": False, "written": len(updates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
