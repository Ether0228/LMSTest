#!/usr/bin/env python3
"""Produce a dry-run plan that attaches read intelligent minutes to term sessions.

Both inputs are JSON exports.  Use a reviewed explicit ``上课日期`` in the
source ledger; the command does not call AI or write to Feishu Base.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from student_ops.course_session_mapper import build_course_source_write_plan


def _records(raw: object) -> list[dict]:
    if isinstance(raw, dict):
        return list(raw.get("来源记录") or raw.get("records") or [])
    return list(raw or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True, help="纪要读取结果；每条需经确认的上课日期")
    parser.add_argument("--term-sessions", type=Path, required=True, help="学期场次Base导出 JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = _records(json.loads(args.sources.read_text(encoding="utf-8")))
    sessions = _records(json.loads(args.term_sessions.read_text(encoding="utf-8")))
    plan = build_course_source_write_plan(sources, sessions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": True, "可写入": len(plan["session_updates"]), "异常": len(plan["exceptions"]), "输出": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
