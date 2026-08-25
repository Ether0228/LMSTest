"""Build private, human-reviewable references from a Schoology process snapshot.

These references deliberately preserve stable IDs but never choose a Base row
from a display name.  A person reviews them before using the separate mapping
apply command.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# The Schoology course title is an official source label, but it is not the
# teaching-system course code.  Keep this tiny, explicit normalization list
# here as well so historic snapshots can be used after the scraper improves.
COURSE_CODE_ALIASES = {
    "G12 Ontario Secondary School Literacy": "OLC4O",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _course_code(value: Any) -> str:
    text = _text(value)
    return COURSE_CODE_ALIASES.get(text, text)


def build_snapshot_references(snapshot: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Return sorted enrollment and grade-item reference rows without writes."""
    sections = {
        _text(row.get("section_nid")): _course_code(row.get("course_code"))
        for row in snapshot.get("course_sections", [])
        if _text(row.get("section_nid"))
    }
    enrollment_keys: set[tuple[str, str, str]] = set()
    enrollments: list[dict[str, str]] = []
    for row in snapshot.get("section_enrollments", []):
        uid, section = _text(row.get("student_uid")), _text(row.get("section_nid"))
        if not uid or not section:
            continue
        key = (uid, section, _text(row.get("role")))
        if key in enrollment_keys:
            continue
        enrollment_keys.add(key)
        enrollments.append({
            "Schoology学生UID": uid,
            "Schoology学生姓名（仅供人工核对）": _text(row.get("student_name")),
            "课程代码": _course_code(row.get("course_code")) or sections.get(section, ""),
            "SchoologySectionNID": section,
            "角色": _text(row.get("role")),
        })
    candidate_keys: set[tuple[str, str]] = set()
    candidates: list[dict[str, str]] = []
    for row in snapshot.get("grade_items", []):
        section, assignment = _text(row.get("section_nid")), _text(row.get("grade_item_nid"))
        if not section or not assignment or (section, assignment) in candidate_keys:
            continue
        candidate_keys.add((section, assignment))
        candidates.append({
            "课程代码": sections.get(section, ""),
            "SchoologySectionNID": section,
            "Schoology作业NID": assignment,
            "作业标题": _text(row.get("title")),
            "满分": _text(row.get("max_points")),
            "截止时间": _text(row.get("due_at")),
            "成绩类别": _text(row.get("category_title")),
        })
    return {
        "enrollments": sorted(enrollments, key=lambda row: (row["Schoology学生UID"], row["SchoologySectionNID"])),
        "course_tasks": sorted(candidates, key=lambda row: (row["课程代码"], row["SchoologySectionNID"], row["Schoology作业NID"])),
    }
