"""Resolve generated and teacher-edited weekly feedback text safely."""
from __future__ import annotations

import copy
from typing import Any, Mapping


TEXT_FIELDS = (
    "课程学习AI草稿", "任务执行AI草稿", "成绩总结AI草稿", "IELTS周总结AI草稿",
    "PBL周总结AI草稿", "本周总体AI草稿", "下周学生行动", "下周学校支持", "智育师修改稿",
)


def _scalar(value: Any) -> Any:
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def resolve_drafts(generated: Mapping[str, Any], base_fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Overlay only non-empty teacher-visible Base text onto generated drafts."""
    resolved = dict(generated)
    for field in TEXT_FIELDS:
        value = _scalar((base_fields or {}).get(field))
        if isinstance(value, str) and value.strip():
            resolved[field] = value.strip()
    return resolved


def apply_feedback_record(payload: Mapping[str, Any], drafts: Mapping[str, Any], record: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare preview/freeze data without turning an unconfirmed action into fact."""
    record = record or {}
    effective_drafts = resolve_drafts(drafts, record)
    result = copy.deepcopy(payload)
    state = set(record.get("反馈状态") or [])
    action, support = effective_drafts.get("下周学生行动"), effective_drafts.get("下周学校支持")
    if state & {"已确认", "已发布"} and (action or support):
        result["confirmed_next_actions"] = [{"action": action or "下周行动待补充", "school_support": support or "学校支持待补充", "confirmation_status": "已确认"}]
    result["反馈状态"] = next(iter(state), result.get("反馈状态", "草稿"))
    return result, effective_drafts
