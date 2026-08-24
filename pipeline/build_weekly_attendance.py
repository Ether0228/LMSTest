#!/usr/bin/env python3
"""Build an anonymous attendance audit preview from lark-cli NDJSON exports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from student_ops.attendance_adapter import build_weekly_attendance_payload
from student_ops.publishing import render_pdf, render_weekly_html


def read_ndjson(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-sessions", type=Path, required=True)
    parser.add_argument("--term-sessions", type=Path, required=True)
    parser.add_argument("--student-term-id", required=True)
    parser.add_argument("--student-alias", default="匿名学生")
    parser.add_argument("--week-number", type=int, required=True)
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--week-end", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    attendance = build_weekly_attendance_payload(
        read_ndjson(args.student_sessions), read_ndjson(args.term_sessions),
        student_term_id=args.student_term_id, week_start=args.week_start,
        week_end=args.week_end, as_of=args.as_of,
    )
    payload = {
        "student": {"id": "anonymous", "name": args.student_alias},
        "week": {"number": args.week_number, "start": args.week_start, "end": args.week_end},
        "report": {"title": "学生周度学习反馈 · 出勤链路审计", "version_label": "只读审计"},
        "attendance": attendance,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = args.output_dir / "weekly_attendance_payload.json"
    audit_path = args.output_dir / "weekly_attendance_audit.json"
    html_path = args.output_dir / "weekly_feedback_preview.html"
    pdf_path = args.output_dir / "weekly_feedback_preview.pdf"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_path.write_text(json.dumps(attendance["audit"], ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_weekly_html(payload, {}), encoding="utf-8")
    render_pdf(html_path, pdf_path)
    print(json.dumps({
        "payload": str(payload_path), "audit": str(audit_path),
        "html": str(html_path), "pdf": str(pdf_path),
        "sessions": len(attendance["sessions"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
