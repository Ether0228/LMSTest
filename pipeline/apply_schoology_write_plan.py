#!/usr/bin/env python3
"""Apply stable-ID Schoology task/grade write plans to Feishu Base.

The plan must be created by ``schoology_adapter.py``.  This command never
resolves names and defaults to a printed dry-run.  Grade event/overall-grade
observations remain append-only review artifacts until their destination table
and business approval are explicitly configured.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


TASK_FIELDS = frozenset({"当前提交状态", "首次提交时间", "最近提交时间"})
GRADE_FIELDS = frozenset({"学生UID", "SectionNID", "作业NID", "所属课程任务", "学生学期任务", "得分", "满分", "老师评语", "更新时间"})


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


def _validate_updates(rows: Iterable[Mapping[str, Any]], allowed: frozenset[str], *, records_required: bool) -> list[dict[str, Any]]:
    valid = []
    for row in rows:
        fields = row.get("fields")
        if not isinstance(fields, Mapping) or not fields:
            raise RuntimeError("schoology_plan_missing_fields")
        if set(fields) - allowed:
            raise RuntimeError("schoology_plan_contains_unapproved_fields")
        if records_required and not row.get("record_id"):
            raise RuntimeError("schoology_task_update_missing_record_id")
        valid.append(dict(row))
    return valid


def validate_plan(plan: Mapping[str, Any], *, allow_partial: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exceptions = list(plan.get("exceptions") or [])
    if exceptions and not allow_partial:
        raise RuntimeError("schoology_plan_contains_exceptions")
    return (
        _validate_updates(plan.get("student_task_updates") or [], TASK_FIELDS, records_required=True),
        _validate_updates(plan.get("grade_updates") or [], GRADE_FIELDS, records_required=False),
    )


def upsert(*, base_token: str, table_id: str, update: Mapping[str, Any], identity: str, profile: str | None) -> None:
    command = ["lark-cli", "base", "+record-upsert", "--base-token", base_token, "--table-id", table_id, "--json", json.dumps(update["fields"], ensure_ascii=False), "--as", identity]
    if update.get("record_id"):
        command.extend(("--record-id", str(update["record_id"])))
    if profile:
        command.extend(("--profile", profile))
    run_cli(command)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--student-task-table-id", default="tbldjuqwBZ9BDbEL")
    parser.add_argument("--grade-table-id", default="tbl0q7Lgbb8RSbeU")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    task_updates, grade_updates = validate_plan(plan, allow_partial=args.allow_partial)
    review_only = {key: plan.get(key, []) for key in ("grade_events", "course_grade_observations", "exceptions")}
    if not args.apply:
        print(json.dumps({"dry_run": True, "student_task_updates": task_updates, "grade_updates": grade_updates, "review_only": review_only}, ensure_ascii=False, indent=2))
        return 0
    for update in task_updates:
        upsert(base_token=args.base_token, table_id=args.student_task_table_id, update=update, identity=args.identity, profile=args.profile)
    for update in grade_updates:
        upsert(base_token=args.base_token, table_id=args.grade_table_id, update=update, identity=args.identity, profile=args.profile)
    print(json.dumps({"dry_run": False, "student_task_written": len(task_updates), "grade_written": len(grade_updates), "review_only": {key: len(value) for key, value in review_only.items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
