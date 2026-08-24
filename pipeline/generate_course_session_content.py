#!/usr/bin/env python3
"""Generate a dry-run 学期场次 AI-candidate write plan from exported Base rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from student_ops.ai import FixtureAIAdapter, OpenAICompatibleAdapter
from student_ops.course_content_generation import build_course_content_generation_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, required=True, help="只含待生成学期场次的 JSON export")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai-mode", choices=("fixture", "live"), default="fixture")
    args = parser.parse_args()
    raw = json.loads(args.sessions.read_text(encoding="utf-8"))
    rows = raw.get("records", raw)
    adapter = FixtureAIAdapter() if args.ai_mode == "fixture" else OpenAICompatibleAdapter.from_environment()
    plan = build_course_content_generation_plan(rows, adapter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": True, "待写入": len(plan["session_updates"]), "异常": len(plan["exceptions"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
