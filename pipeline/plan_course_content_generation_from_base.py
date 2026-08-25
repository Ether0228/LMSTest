#!/usr/bin/env python3
"""Read pending session sources from Base and produce AI candidate updates only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from collect_weekly_feedback_base_facts import list_records
from student_ops.ai import FixtureAIAdapter, OpenAICompatibleAdapter
from student_ops.course_content_generation import build_course_content_generation_plan


TABLE_ID = "tbllrHXPQrAcRfCR"
FIELDS = ("课程编码", "内容生成状态", "内容来源文本", "内容确认状态")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai-mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    rows = list_records(
        base_token=args.base_token, table_id=TABLE_ID, fields=FIELDS, identity=args.identity, profile=args.profile,
        filter_json={"logic": "and", "conditions": [["内容生成状态", "intersects", ["待生成"]]]},
    )
    adapter = FixtureAIAdapter() if args.ai_mode == "fixture" else OpenAICompatibleAdapter.from_environment()
    plan = build_course_content_generation_plan(rows, adapter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": True, "已读取待生成场次": len(rows), "待写入AI候选": len(plan["session_updates"]), "异常": len(plan["exceptions"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
