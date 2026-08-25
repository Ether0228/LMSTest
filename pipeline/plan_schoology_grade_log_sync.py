#!/usr/bin/env python3
"""Build a no-write Schoology score-log sync plan for selected student terms.

The caller supplies Base student-term record IDs.  We never infer which term a
Schoology user belongs to from a display name, semester label, or enrollment.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from collect_weekly_feedback_base_facts import list_records
from student_ops.schoology_adapter import build_schoology_write_plan


TABLES = {
    "学生学期": "tblzZy2DoDWLs4LP",
    "课程任务": "tblMzgO5ZDvWTtuO",
    "学生任务": "tbldjuqwBZ9BDbEL",
    "学生分数": "tbl0q7Lgbb8RSbeU",
}


def _scalar(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _text(value) -> str:
    return str(_scalar(value) or "").strip()


def _link_filter(field: str, record_ids: list[str]) -> dict:
    return {"logic": "and", "conditions": [[field, "intersects", [{"id": record_id} for record_id in record_ids]]]}


def build_bulk_plan(*, snapshot: dict, selected_terms: list[dict], course_tasks: list[dict], student_tasks: list[dict], grade_records: list[dict]) -> dict:
    seen_uids = Counter(_text(row.get("Schoology学生UID")) for row in selected_terms if _text(row.get("Schoology学生UID")))
    combined = {"student_task_updates": [], "grade_updates": [], "grade_events": [], "course_grade_observations": [], "exceptions": [], "skipped": []}
    for term in selected_terms:
        student_term_id, uid = str(term.get("record_id") or ""), _text(term.get("Schoology学生UID"))
        if not uid:
            combined["skipped"].append({"student_term_id": student_term_id, "类型": "缺少Schoology学生UID"})
            continue
        if seen_uids[uid] > 1:
            combined["exceptions"].append({"student_term_id": student_term_id, "类型": "Schoology学生UID对应多个学生学期", "Schoology学生UID": uid})
            continue
        tasks = [row for row in student_tasks if _text((row.get("任务归属学生") or [{}])[0].get("id") if isinstance(row.get("任务归属学生"), list) and row.get("任务归属学生") else "") == student_term_id]
        task_ids = {str(row.get("record_id") or "") for row in tasks}
        grades = [row for row in grade_records if _text((row.get("学生学期任务") or [{}])[0].get("id") if isinstance(row.get("学生学期任务"), list) and row.get("学生学期任务") else "") in task_ids]
        plan = build_schoology_write_plan(snapshot, student_uid=uid, student_term_id=student_term_id, course_task_records=course_tasks, student_task_records=tasks, grade_records=grades)
        for key in ("student_task_updates", "grade_updates", "grade_events", "course_grade_observations", "exceptions"):
            combined[key].extend(plan[key])
    combined["统计"] = {key: len(combined[key]) for key in ("student_task_updates", "grade_updates", "grade_events", "course_grade_observations", "exceptions", "skipped")}
    return combined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--schoology-snapshot", type=Path, required=True)
    parser.add_argument("--student-term-record-id", action="append", required=True, help="可重复传入；只同步人工指定的学生学期")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    terms = list_records(base_token=args.base_token, table_id=TABLES["学生学期"], fields=("Schoology学生UID",), identity=args.identity, profile=args.profile)
    requested = set(args.student_term_record_id)
    selected = [row for row in terms if row["record_id"] in requested]
    missing = requested - {row["record_id"] for row in selected}
    if missing:
        parser.error(f"未知学生学期record_id：{','.join(sorted(missing))}")
    course_tasks = list_records(base_token=args.base_token, table_id=TABLES["课程任务"], fields=("SchoologySectionNID", "Schoology作业NID"), identity=args.identity, profile=args.profile)
    student_tasks = list_records(base_token=args.base_token, table_id=TABLES["学生任务"], fields=("任务归属学生", "所属课程任务"), identity=args.identity, profile=args.profile, filter_json=_link_filter("任务归属学生", list(requested)))
    task_ids = [row["record_id"] for row in student_tasks]
    grade_records = [] if not task_ids else list_records(base_token=args.base_token, table_id=TABLES["学生分数"], fields=("学生UID", "SectionNID", "作业NID", "所属课程任务", "学生学期任务", "得分", "满分", "老师评语", "更新时间", "分数变化日志"), identity=args.identity, profile=args.profile, filter_json=_link_filter("学生学期任务", task_ids))
    plan = build_bulk_plan(snapshot=json.loads(args.schoology_snapshot.read_text(encoding="utf-8")), selected_terms=selected, course_tasks=course_tasks, student_tasks=student_tasks, grade_records=grade_records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": True, "output": str(args.output), **plan["统计"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
