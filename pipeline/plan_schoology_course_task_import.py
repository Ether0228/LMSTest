#!/usr/bin/env python3
"""Create a no-write review plan for importing Schoology gradebook tasks.

This deliberately does not create Base records.  A Schoology grade item proves
that an assessable item exists, but does not by itself establish the teaching
task type, weighting policy, or which Base course offering owns it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from collect_weekly_feedback_base_facts import list_records
from student_ops.schoology_snapshot_reference import build_snapshot_references


COURSE_TABLE_ID = "tbl6mhwb9GIrycF4"
COURSE_TASK_TABLE_ID = "tblMzgO5ZDvWTtuO"


def scalar(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def text(value) -> str:
    return str(scalar(value) or "").strip()


def build_import_plan(*, snapshot: dict, base_courses: list[dict], base_tasks: list[dict], semester: str) -> dict:
    references = build_snapshot_references(snapshot)
    course_codes = {text(row.get("课程")) for row in base_courses if text(row.get("课程"))}
    known_ids = {
        (text(row.get("SchoologySectionNID")), text(row.get("Schoology作业NID")))
        for row in base_tasks
        if text(row.get("SchoologySectionNID")) and text(row.get("Schoology作业NID"))
    }
    missing_courses = sorted({row["课程代码"] for row in references["course_tasks"] if row["课程代码"] and row["课程代码"] not in course_codes})
    candidates = []
    for row in references["course_tasks"]:
        stable_id = (row["SchoologySectionNID"], row["Schoology作业NID"])
        if stable_id in known_ids:
            disposition = "已存在，跳过"
        elif row["课程代码"] not in course_codes:
            disposition = "阻塞：课程尚未在学期课程建档"
        else:
            disposition = "待课程负责人确认后创建"
        candidates.append({
            **row,
            "拟写入所属学期": semester,
            "拟写入任务类型": "待课程负责人确认（不得由系统推断）",
            "处理结论": disposition,
        })
    return {
        "规则": [
            "仅使用 SchoologySectionNID + Schoology作业NID 去重，不以标题或姓名匹配。",
            "不会自动创建课程任务，也不会把模拟任务写成真实 Schoology 任务。",
            "缺失的学期课程需要由课程/排课负责人补充教师、时段、校区后建档。",
        ],
        "Base已建学期课程": sorted(course_codes),
        "待建学期课程": missing_courses,
        "课程任务候选": candidates,
        "统计": {
            "候选总数": len(candidates),
            "已存在": sum(row["处理结论"] == "已存在，跳过" for row in candidates),
            "可供确认": sum(row["处理结论"] == "待课程负责人确认后创建" for row in candidates),
            "受课程建档阻塞": sum(row["处理结论"] == "阻塞：课程尚未在学期课程建档" for row in candidates),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--schoology-snapshot", type=Path, required=True)
    parser.add_argument("--semester", required=True, help="仅作为待确认的拟写入值，例如 26-S6")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    snapshot = json.loads(args.schoology_snapshot.read_text(encoding="utf-8"))
    courses = list_records(base_token=args.base_token, table_id=COURSE_TABLE_ID, fields=("课程",), identity=args.identity, profile=args.profile)
    tasks = list_records(base_token=args.base_token, table_id=COURSE_TASK_TABLE_ID, fields=("SchoologySectionNID", "Schoology作业NID"), identity=args.identity, profile=args.profile)
    plan = build_import_plan(snapshot=snapshot, base_courses=courses, base_tasks=tasks, semester=args.semester)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **plan["统计"], "待建学期课程": plan["待建学期课程"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
