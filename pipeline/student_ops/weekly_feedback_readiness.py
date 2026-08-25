"""Pure readiness assessment for the real weekly-feedback V1 gate."""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping


def _scalar(value: Any) -> Any:
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _text(row: Mapping[str, Any], field: str) -> str:
    return str(_scalar(row.get(field)) or "").strip()


def assess_readiness(*, env: Mapping[str, bool], students: Iterable[Mapping[str, Any]], course_tasks: Iterable[Mapping[str, Any]], term_sessions: Iterable[Mapping[str, Any]], as_of: str) -> dict[str, Any]:
    cutoff = date.fromisoformat(as_of)
    students, course_tasks, term_sessions = list(students), list(course_tasks), list(term_sessions)
    student_uid = sum(bool(_text(row, "Schoology学生UID")) for row in students)
    section_ids = sum(bool(_text(row, "SchoologySectionNID")) for row in course_tasks)
    assignment_ids = sum(bool(_text(row, "Schoology作业NID")) for row in course_tasks)
    ended = [row for row in term_sessions if _text(row, "上课日期")[:10] and date.fromisoformat(_text(row, "上课日期")[:10]) <= cutoff]
    confirmed = sum(_text(row, "内容确认状态") == "已确认" for row in ended)
    gates = {
        "live_ai": all(env.get(name, False) for name in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL")),
        "schoology_runtime": (
            bool(env.get("SCHOOLOGY_COOKIES"))
            and bool(env.get("SCHOOLOGY_SECTION_NIDS") or env.get("SCHOOLOGY_SECTION_NID"))
        ) or bool(env.get("SCHOOLOGY_SNAPSHOT")),
        "schoology_student_uid": student_uid > 0,
        "schoology_course_mapping": section_ids > 0 and assignment_ids > 0,
        "ended_confirmed_course_content": confirmed > 0,
    }
    return {
        "as_of": as_of,
        "gates": gates,
        "counts": {
            "学生SchoologyUID": {"已填": student_uid, "总数": len(students)},
            "课程任务SectionNID": {"已填": section_ids, "总数": len(course_tasks)},
            "课程任务作业NID": {"已填": assignment_ids, "总数": len(course_tasks)},
            "已结束学期场次": len(ended),
            "已确认课程内容": confirmed,
        },
        "ready_for_real_e2e": all(gates.values()),
        "next_blockers": [name for name, value in gates.items() if not value],
    }
