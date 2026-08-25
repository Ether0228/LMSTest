"""Map a discovered intelligent-minute source to one scheduled term session.

Matching a message timestamp to a lesson is unsafe: a teacher can post a
minute before or after the meeting.  This module therefore requires an
explicit ``上课日期`` from the source/reviewer and accepts a mapping only when
semester, course code and date select exactly one ``学期场次`` record.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def _date(value: Any) -> str:
    raw = _scalar(value)
    return str(raw)[:10] if raw else ""


def _text(value: Any) -> str:
    return str(_scalar(value) or "").strip()


def build_course_source_write_plan(
    sources: Iterable[Mapping[str, Any]], term_sessions: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return Base-safe updates and explicit exceptions; never guess a match."""
    indexed: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for session in term_sessions:
        key = (_text(session.get("学期")), _text(session.get("课程编码")), _date(session.get("上课日期")))
        if all(key):
            indexed.setdefault(key, []).append(session)

    plan: dict[str, list[dict[str, Any]]] = {"session_updates": [], "exceptions": []}
    seen_tokens: set[str] = set()
    for source in sources:
        token = _text(source.get("文档token"))
        if not token:
            plan["exceptions"].append({"类型": "缺少智能纪要文档token", "source": dict(source)})
            continue
        if token in seen_tokens:
            plan["exceptions"].append({"类型": "重复智能纪要文档token", "文档token": token})
            continue
        seen_tokens.add(token)
        key = (_text(source.get("学期")), _text(source.get("课程编码")), _date(source.get("上课日期")))
        if not key[2]:
            plan["exceptions"].append({
                "类型": "待补实际上课日期", "文档token": token,
                "课程编码": key[1], "学期": key[0],
                "说明": "消息发送时间不能作为上课日期；请从纪要或老师确认中补充。",
            })
            continue
        matches = indexed.get(key, [])
        if len(matches) != 1:
            plan["exceptions"].append({
                "类型": "学期场次无法唯一匹配", "文档token": token,
                "匹配键": {"学期": key[0], "课程编码": key[1], "上课日期": key[2]},
                "候选场次数": len(matches),
                "候选record_id": [str(row.get("record_id") or "") for row in matches],
            })
            continue
        session = matches[0]
        existing_url = _text(session.get("内容来源链接"))
        source_url = _text(source.get("智能纪要URL"))
        if existing_url and existing_url != source_url:
            plan["exceptions"].append({
                "类型": "场次已有不同内容来源", "文档token": token, "学期场次record_id": str(session["record_id"]),
                "已有来源": existing_url, "待写入来源": source_url,
            })
            continue
        fields = {
            "内容来源类型": ["智能纪要"],
            # 当前 Base 字段是文本，不能写入富文本 URL 对象。
            "内容来源链接": source_url,
            "内容来源文本": source.get("正文"),
            "内容生成状态": ["待生成"],
            "内容生成异常": None,
            "内容Schema版本": "session_minutes_v1",
        }
        plan["session_updates"].append({
            "record_id": str(session["record_id"]),
            "fields": {name: value for name, value in fields.items() if value not in (None, "")},
            "source": {"文档token": token, "上课日期": key[2]},
        })
    return plan
