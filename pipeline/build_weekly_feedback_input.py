#!/usr/bin/env python3
"""Build one real weekly-feedback workflow input from reviewed Base JSON exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from student_ops.weekly_feedback_base_input import build_weekly_feedback_input


def records(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("records") or raw.get("data", {}).get("records") or raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-term", type=Path, required=True, help="只含目标学生学期的 Base JSON 导出")
    parser.add_argument("--student-name", required=True)
    parser.add_argument("--week", required=True, help="例如 第1周 或 1")
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--week-end", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--student-sessions", type=Path, required=True)
    parser.add_argument("--term-sessions", type=Path, required=True)
    parser.add_argument("--student-tasks", type=Path, required=True)
    parser.add_argument("--grades", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--term", default="")
    parser.add_argument("--educator", default="")
    args = parser.parse_args()
    term_rows = records(args.student_term)
    if len(term_rows) != 1:
        raise ValueError("student_term_export_must_contain_exactly_one_record")
    result = build_weekly_feedback_input(
        student_term=term_rows[0], student_name=args.student_name, week_label=args.week,
        week_start=args.week_start, week_end=args.week_end, as_of=args.as_of,
        student_sessions=records(args.student_sessions), term_sessions=records(args.term_sessions),
        student_tasks=records(args.student_tasks), grade_records=records(args.grades),
        report_term=args.term, educator=args.educator,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "反馈唯一键": f"{term_rows[0]['record_id']}:{result['week']['number']}", "场次数": len(result['base_attendance']['student_session_records'])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
