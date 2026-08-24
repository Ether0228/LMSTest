"""Pure mapping from a validated weekly payload to editable Base fields.

This module deliberately does not call the Base API.  It gives the server and
the Base preview exactly one write contract, and makes it impossible for the
HTML renderer to silently use a different text version from the editable Base
record.
"""
from __future__ import annotations

from typing import Any, Mapping


EDITABLE_DRAFT_FIELDS = (
    "课程学习AI草稿",
    "任务执行AI草稿",
    "成绩总结AI草稿",
    "IELTS周总结AI草稿",
    "PBL周总结AI草稿",
    "本周总体AI草稿",
)


def _integrity_status(module_states: Mapping[str, str]) -> str:
    """Map workflow states to the select options installed in 学生周反馈."""
    states = set(module_states.values())
    if "blocked" in states or "failed" in states:
        return "待处理"
    if "partial" in states or "missing_source" in states or "ai_failed" in states:
        return "部分可用"
    return "数据准备"


def _warnings(module_states: Mapping[str, str], warnings: list[str]) -> str:
    unavailable = [name for name, state in sorted(module_states.items()) if state not in ("success",)]
    items = ([f"模块状态：{', '.join(unavailable)}"] if unavailable else []) + list(warnings)
    return "\n".join(dict.fromkeys(item for item in items if item))


def build_weekly_feedback_fields(
    payload: Mapping[str, Any],
    drafts_result: Mapping[str, Any] | None = None,
    *,
    educator_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return only writable cells for the 学生周反馈 Base record.

    ``educator_overrides`` is intentionally limited to textual draft fields:
    it lets a preview save teacher edits without changing deterministic facts.
    Confirmation and publication are handled by a later, explicit server
    transition and are therefore absent from this pre-review update.
    """
    module_states = dict(payload.get("data_integrity", {}))
    drafts = {}
    warnings: list[str] = []
    if drafts_result:
        drafts = dict(drafts_result.get("payload", {}).get("drafts", {}))
        warnings = list(drafts_result.get("warnings", []))
    overrides = dict(educator_overrides or {})
    unknown = set(overrides) - set(EDITABLE_DRAFT_FIELDS) - {"下周学生行动", "下周学校支持", "智育师修改稿", "老师补充"}
    if unknown:
        raise ValueError(f"不允许通过预览写入字段：{', '.join(sorted(unknown))}")

    fields: dict[str, Any] = {
        "反馈唯一键": payload["反馈唯一键"],
        "教学周": str(payload["week"]["number"]),
        "数据完整性状态": [_integrity_status(module_states)],
        "缺失/冲突摘要": _warnings(module_states, warnings) or None,
        "反馈状态": ["草稿"],
    }
    for field in EDITABLE_DRAFT_FIELDS:
        candidate = overrides.get(field, drafts.get(field))
        if candidate:
            fields[field] = candidate
    for field in ("下周学生行动", "下周学校支持", "智育师修改稿", "老师补充"):
        if field in overrides:
            fields[field] = overrides[field]
    return fields


def build_publication_fields(*, version: str, published_at: str, html_url: str, pdf_url: str) -> dict[str, Any]:
    """Cells written only after a human-confirmed server publication."""
    if not all((version, published_at, html_url, pdf_url)):
        raise ValueError("发布字段不完整")
    return {
        "反馈状态": ["已发布"],
        "发布版本": version,
        "发布时间": published_at,
        "网页链接": html_url,
        "PDF链接": pdf_url,
        "撤销状态": ["有效"],
    }
