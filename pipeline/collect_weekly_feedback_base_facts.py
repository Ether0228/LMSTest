#!/usr/bin/env python3
"""Read the minimum Base facts for one ``学生学期 + 教学周`` into workflow input.

This command is read-only.  It filters locally after Base retrieval because a
Link-field filter must never be guessed from a display name.  Only records
whose Link IDs prove the target student term are written to its output folder.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from student_ops.weekly_feedback_base_input import _link_id, _scalar, _week_number, build_weekly_feedback_input


BASE_TABLES = {
    "学生场次": "tbl7A83OXf3kQvpR",
    "学期场次": "tbllrHXPQrAcRfCR",
    "学生任务": "tbldjuqwBZ9BDbEL",
    "学生分数": "tbl0q7Lgbb8RSbeU",
}
FIELDS = {
    "学生场次": ("学生学期", "学期场次", "教学周", "上课日期", "时间", "课程编码", "场次类别", "学生场次唯一键", "学生校区", "线上出勤情况", "线下出勤情况", "线下出勤教室", "摄像头开启状态", "互动情况", "互动内容"),
    "学期场次": ("课程编码", "上课日期", "时间", "场次类别", "内容确认状态", "课程内容总结", "内容确认人", "内容确认时间"),
    "学生任务": ("任务归属学生", "课程", "所属模块", "任务标题", "作业名称", "所属课程任务", "截止日期", "补做Deadline", "返工Deadline", "当前提交状态", "检查状态", "老师评语"),
    "学生分数": ("学生学期任务", "课程", "作业名", "得分", "满分", "老师评语", "更新时间"),
}


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


def rows_from_matrix(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = response["data"]
    return [{"record_id": record_id, **dict(zip(data["fields"], row))} for record_id, row in zip(data["record_id_list"], data["data"])]


def list_records(*, base_token: str, table_id: str, fields: Iterable[str], identity: str, profile: str | None) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    offset = 0
    # The installed CLI uses offset pagination (not ``--page-all``).  Keep
    # each request bounded and terminate from the API's explicit has_more.
    while True:
        command = ["lark-cli", "base", "+record-list", "--base-token", base_token, "--table-id", table_id, "--offset", str(offset), "--limit", "200", "--as", identity, "--format", "json"]
        for field in fields:
            command.extend(("--field-id", field))
        if profile:
            command.extend(("--profile", profile))
        response = run_cli(command)
        rows = rows_from_matrix(response)
        all_rows.extend(rows)
        if not response["data"].get("has_more"):
            return all_rows
        if not rows:
            raise RuntimeError("base_pagination_stalled")
        offset += len(rows)


def selected_student_sessions(rows: Iterable[Mapping[str, Any]], *, student_term_id: str, week_number: int) -> list[dict[str, Any]]:
    expected = {str(week_number), f"第{week_number}周"}
    return [dict(row) for row in rows if _link_id(row, "学生学期") == student_term_id and str(_scalar(row.get("教学周")) or "") in expected]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--student-term-record-id", required=True)
    parser.add_argument("--student-name", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--week-end", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--term", default="")
    parser.add_argument("--educator", default="")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    week_number = _week_number(args.week)
    student_sessions = selected_student_sessions(
        list_records(base_token=args.base_token, table_id=BASE_TABLES["学生场次"], fields=FIELDS["学生场次"], identity=args.identity, profile=args.profile),
        student_term_id=args.student_term_record_id, week_number=week_number,
    )
    term_ids = {_link_id(row, "学期场次") for row in student_sessions}
    term_sessions = [row for row in list_records(base_token=args.base_token, table_id=BASE_TABLES["学期场次"], fields=FIELDS["学期场次"], identity=args.identity, profile=args.profile) if row["record_id"] in term_ids]
    student_tasks = [row for row in list_records(base_token=args.base_token, table_id=BASE_TABLES["学生任务"], fields=FIELDS["学生任务"], identity=args.identity, profile=args.profile) if _link_id(row, "任务归属学生") == args.student_term_record_id]
    task_ids = {row["record_id"] for row in student_tasks}
    grade_records = [row for row in list_records(base_token=args.base_token, table_id=BASE_TABLES["学生分数"], fields=FIELDS["学生分数"], identity=args.identity, profile=args.profile) if _link_id(row, "学生学期任务") in task_ids]
    payload = build_weekly_feedback_input(
        student_term={"record_id": args.student_term_record_id}, student_name=args.student_name, week_label=week_number,
        week_start=args.week_start, week_end=args.week_end, as_of=args.as_of,
        student_sessions=student_sessions, term_sessions=term_sessions, student_tasks=student_tasks, grade_records=grade_records,
        report_term=args.term, educator=args.educator,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, records in (("student_sessions", student_sessions), ("term_sessions", term_sessions), ("student_tasks", student_tasks), ("grade_records", grade_records)):
        (args.output_dir / f"{name}.json").write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    output = args.output_dir / "weekly_feedback_input.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"read_only": True, "output": str(output), "学生场次": len(student_sessions), "学期场次": len(term_sessions), "学生任务": len(student_tasks), "学生分数": len(grade_records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
