#!/usr/bin/env python3
"""Export Base rows for human-reviewed Schoology stable-ID mapping."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from collect_weekly_feedback_base_facts import list_records


def scalar(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    students = list_records(base_token=args.base_token, table_id="tbl9PhF99dUkTU1A", fields=("学生姓名", "Schoology学生UID"), identity=args.identity, profile=args.profile)
    tasks = list_records(base_token=args.base_token, table_id="tblMzgO5ZDvWTtuO", fields=("课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID"), identity=args.identity, profile=args.profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    student_path, task_path = args.output_dir / "schoology_students_mapping.csv", args.output_dir / "schoology_course_tasks_mapping.csv"
    with student_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=("record_id", "学生姓名", "Schoology学生UID"))
        writer.writeheader()
        writer.writerows({"record_id": row["record_id"], "学生姓名": scalar(row.get("学生姓名")) or "", "Schoology学生UID": scalar(row.get("Schoology学生UID")) or ""} for row in students)
    with task_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=("record_id", "课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID"))
        writer.writeheader()
        writer.writerows({field: scalar(row.get(field)) or "" for field in ("课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID")} | {"record_id": row["record_id"]} for row in tasks)
    print(f"students={len(students)} tasks={len(tasks)} output={args.output_dir}")


if __name__ == "__main__":
    main()
