"""Discover intelligent-minute Docx links from registered course-group messages.

The module is intentionally a discovery ledger, not a matching heuristic.  A
discovered document is only a candidate source until a later mapper can match
it to exactly one 学期场次 by course, term and lesson date.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


DOCX_URL = re.compile(r"https?://[^\s)\]}>]+/docx/([A-Za-z0-9_-]+)(?:\?[^\s)\]}>]*)?")


def docx_links(content: str) -> list[tuple[str, str]]:
    """Return ordered, unique (url, token) pairs; never treat non-docx links as minutes."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in DOCX_URL.finditer(content or ""):
        url, token = match.group(0), match.group(1)
        if token not in seen:
            seen.add(token)
            found.append((url, token))
    return found


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def discover_smart_minutes(
    messages: Iterable[Mapping[str, Any]], registry: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Produce append-only source rows from raw IM messages and a group registry."""
    active = {str(row["chat_id"]): row for row in registry if row.get("启用", True)}
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        chat_id = str(_scalar(message.get("chat_id")) or message.get("chat_id") or "")
        group = active.get(chat_id)
        if not group or message.get("deleted"):
            continue
        for url, token in docx_links(str(message.get("content") or "")):
            key = (str(message.get("message_id") or ""), token)
            if not key in seen:
                seen.add(key)
                output.append({
                    "学期": group.get("学期"),
                    "课程编码": group.get("课程编码"),
                    "教师": group.get("教师"),
                    "chat_id": chat_id,
                    "消息ID": message.get("message_id"),
                    "消息发送时间": message.get("create_time"),
                    "智能纪要URL": url,
                    "文档token": token,
                    "来源状态": "待场次匹配",
                })
    return output
