#!/usr/bin/env python3
"""Create/apply a reviewed Schoology stable-ID Base mapping plan from CSVs."""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from student_ops.schoology_mapping import build_mapping_write_plan


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def run_cli(command):
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    response = json.loads(raw)
    if completed.returncode or not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "lark_cli_failed"))
    return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--students", type=Path, required=True)
    parser.add_argument("--course-tasks", type=Path, required=True)
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = build_mapping_write_plan(read_csv(args.students), read_csv(args.course_tasks))
    if plan["exceptions"]:
        raise RuntimeError("schoology_mapping_plan_contains_exceptions")
    if not args.apply:
        print(json.dumps({"dry_run": True, **plan}, ensure_ascii=False, indent=2))
        return 0
    for table_id, updates in (("tbl9PhF99dUkTU1A", plan["student_updates"]), ("tblMzgO5ZDvWTtuO", plan["course_task_updates"])):
        for update in updates:
            command = ["lark-cli", "base", "+record-upsert", "--base-token", args.base_token, "--table-id", table_id, "--record-id", update["record_id"], "--json", json.dumps(update["fields"], ensure_ascii=False), "--as", args.identity]
            if args.profile:
                command.extend(("--profile", args.profile))
            run_cli(command)
    print(json.dumps({"dry_run": False, "students": len(plan["student_updates"]), "course_tasks": len(plan["course_task_updates"])}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
