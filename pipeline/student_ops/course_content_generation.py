"""Generate non-confirmed six-section course-content candidates from Base facts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .engine import parse_six_sections, validate_session_minutes
from .prompts import SESSION_COURSE_MINUTES_PROMPT_V1


def _scalar(value: Any) -> Any:
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(_scalar(row.get(field)) or "").strip()


def build_course_content_generation_plan(records: Iterable[Mapping[str, Any]], ai_adapter: Any) -> dict[str, list[dict[str, Any]]]:
    """Return write plan; candidates remain unconfirmed even on AI success."""
    updates, exceptions = [], []
    for row in records:
        record_id = str(row.get("record_id") or "")
        if not record_id:
            exceptions.append({"类型": "缺少学期场次record_id"})
            continue
        if _text(row, "内容生成状态") != "待生成":
            continue
        source = _text(row, "内容来源文本")
        if not source:
            updates.append({"record_id": record_id, "fields": {"内容生成状态": ["缺少来源"], "内容生成异常": "内容来源文本为空"}})
            continue
        try:
            candidate = ai_adapter.generate(
                system=SESSION_COURSE_MINUTES_PROMPT_V1,
                user=f"课程：{_text(row, '课程编码')}\n场次：{record_id}\n\n已确认纪要来源：\n{source}",
                fixture_response=_text(row, "mock_ai_response") or None,
            )
            sections, errors = parse_six_sections(candidate)
            errors += validate_session_minutes(candidate, sections)
            if errors:
                updates.append({"record_id": record_id, "fields": {"内容生成状态": ["生成失败"], "内容生成异常": "; ".join(errors)}})
                continue
            updates.append({"record_id": record_id, "fields": {
                "课程内容AI候选": candidate,
                "课程内容结构化结果": json.dumps(sections, ensure_ascii=False),
                "内容生成状态": ["已生成"],
                "内容生成异常": None,
                "内容Schema版本": "session_course_minutes_v1",
                "内容生成时间": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "内容确认状态": ["待确认"],
            }})
        except Exception:  # adapters expose safe error categories; do not leak provider output.
            updates.append({"record_id": record_id, "fields": {"内容生成状态": ["生成失败"], "内容生成异常": "ai_generation_failed"}})
    return {"session_updates": updates, "exceptions": exceptions}
