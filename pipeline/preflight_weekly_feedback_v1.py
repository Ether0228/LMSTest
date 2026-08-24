#!/usr/bin/env python3
"""Read-only V1 readiness check; reports configuration state without secrets."""
from __future__ import annotations

import argparse
import json
import os

from collect_weekly_feedback_base_facts import BASE_TABLES, list_records
from student_ops.weekly_feedback_readiness import assess_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    env = {name: bool(os.environ.get(name, "").strip()) for name in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "SCHOOLOGY_COOKIES", "SCHOOLOGY_SECTION_NIDS", "SCHOOLOGY_SECTION_NID")}
    students = list_records(base_token=args.base_token, table_id="tbl9PhF99dUkTU1A", fields=("Schoology学生UID",), identity=args.identity, profile=args.profile)
    course_tasks = list_records(base_token=args.base_token, table_id="tblMzgO5ZDvWTtuO", fields=("SchoologySectionNID", "Schoology作业NID"), identity=args.identity, profile=args.profile)
    sessions = list_records(base_token=args.base_token, table_id=BASE_TABLES["学期场次"], fields=("上课日期", "内容确认状态"), identity=args.identity, profile=args.profile)
    report = assess_readiness(env=env, students=students, course_tasks=course_tasks, term_sessions=sessions, as_of=args.as_of)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready_for_real_e2e"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
