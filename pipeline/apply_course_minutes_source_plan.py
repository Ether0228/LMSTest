#!/usr/bin/env python3
"""Apply a reviewed course-minute mapping plan to 学期场次, guarded by default."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


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


def validate_plan(plan: dict[str, Any], *, allow_partial: bool) -> list[dict[str, Any]]:
    updates, exceptions = list(plan.get("session_updates") or []), list(plan.get("exceptions") or [])
    if exceptions and not allow_partial:
        raise RuntimeError("course_source_plan_contains_exceptions")
    if any(not row.get("record_id") or not row.get("fields") for row in updates):
        raise RuntimeError("course_source_plan_invalid_update")
    return updates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", default="tbllrHXPQrAcRfCR")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    parser.add_argument("--allow-partial", action="store_true", help="required when the reviewed plan also contains unmatched/conflicting sources")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    updates = validate_plan(plan, allow_partial=args.allow_partial)
    if not args.apply:
        print(json.dumps({"dry_run": True, "updates": updates, "exceptions": plan.get("exceptions", [])}, ensure_ascii=False, indent=2))
        return 0
    written = []
    for update in updates:
        command = ["lark-cli", "base", "+record-upsert", "--base-token", args.base_token, "--table-id", args.table_id, "--record-id", update["record_id"], "--json", json.dumps(update["fields"], ensure_ascii=False), "--as", args.identity]
        if args.profile:
            command.extend(("--profile", args.profile))
        run_cli(command)
        written.append(update["record_id"])
    print(json.dumps({"dry_run": False, "written": len(written), "record_ids": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
