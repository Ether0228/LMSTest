#!/usr/bin/env python3
"""Export Base rows for human-reviewed Schoology stable-ID mapping."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from collect_weekly_feedback_base_facts import list_records
from student_ops.schoology_snapshot_reference import build_snapshot_references


def scalar(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--schoology-snapshot", type=Path, help="private latest.json from the read-only Schoology probe")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    students = list_records(base_token=args.base_token, table_id="tbl9PhF99dUkTU1A", fields=("学生姓名", "Schoology学生UID"), identity=args.identity, profile=args.profile)
    tasks = list_records(base_token=args.base_token, table_id="tblMzgO5ZDvWTtuO", fields=("课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID"), identity=args.identity, profile=args.profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    student_path, task_path = args.output_dir / "schoology_students_mapping.csv", args.output_dir / "schoology_course_tasks_mapping.csv"
    write_csv(student_path, ({"record_id": row["record_id"], "学生姓名": scalar(row.get("学生姓名")) or "", "Schoology学生UID": scalar(row.get("Schoology学生UID")) or ""} for row in students), ("record_id", "学生姓名", "Schoology学生UID"))
    write_csv(task_path, ({field: scalar(row.get(field)) or "" for field in ("课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID")} | {"record_id": row["record_id"]} for row in tasks), ("record_id", "课程编号", "作业标题", "SchoologySectionNID", "Schoology作业NID"))
    summary = {"students": len(students), "tasks": len(tasks), "output": str(args.output_dir)}
    if args.schoology_snapshot:
        references = build_snapshot_references(json.loads(args.schoology_snapshot.read_text(encoding="utf-8")))
        enrollment_path = args.output_dir / "schoology_enrollment_reference.csv"
        candidate_path = args.output_dir / "schoology_course_task_candidates.csv"
        write_csv(enrollment_path, references["enrollments"], ("Schoology学生UID", "Schoology学生姓名（仅供人工核对）", "课程代码", "SchoologySectionNID", "角色"))
        write_csv(candidate_path, references["course_tasks"], ("课程代码", "SchoologySectionNID", "Schoology作业NID", "作业标题", "满分", "截止时间", "成绩类别"))
        summary.update({"enrollment_references": len(references["enrollments"]), "course_task_candidates": len(references["course_tasks"])})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
