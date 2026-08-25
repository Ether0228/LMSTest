"""Translate the existing Schoology process snapshot into Base write plans.

The adapter never matches by display name.  Student UID + Section NID +
assignment NID are the only automatic keys.  Any missing mapping is returned
as an exception instead of creating a guessed task or grade record.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def _link_id(record: Mapping[str, Any], field: str) -> str | None:
    values = record.get(field) or []
    if len(values) == 1 and isinstance(values[0], Mapping):
        return str(values[0].get("id") or "") or None
    return None


def _submission_state(status: str | None) -> str:
    value = (status or "").lower()
    if "resubmit" in value or "重新提交" in value:
        return "已重新提交"
    if value and value not in {"none", "missing", "未提交"}:
        return "已提交"
    return "未提交"


def _course_task_key(record: Mapping[str, Any]) -> tuple[str, str] | None:
    section = str(_scalar(record.get("SchoologySectionNID")) or "")
    assignment = str(_scalar(record.get("Schoology作业NID")) or "")
    return (section, assignment) if section and assignment else None


def _same(left: Any, right: Any) -> bool:
    """Compare Base scalars without treating ``80`` and ``80.0`` as a change."""
    left, right = _scalar(left), _scalar(right)
    if left is None or right is None:
        return left is right
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left).strip() == str(right).strip()


def _change_log(existing: Mapping[str, Any] | None, grade: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return an append-only, human-readable grade observation when facts changed."""
    score, maximum, comment = grade.get("score"), grade.get("max_points"), grade.get("comment_text")
    observed = str(grade.get("observed_at") or "未知同步时间")
    if not existing:
        kind = "首次同步"
    else:
        changed_score = not _same(existing.get("得分"), score) or not _same(existing.get("满分"), maximum)
        changed_comment = not _same(existing.get("老师评语"), comment)
        if not changed_score and not changed_comment:
            return None
        kind = "分数更新" if changed_score else "老师评语更新"
    score_text = "得分未提供" if score is None else f"得分 {score}/{maximum if maximum is not None else '满分未提供'}"
    comment_text = f"；评语：{str(comment).strip()}" if comment not in (None, "") else ""
    return kind, f"{observed}｜{kind}｜{score_text}{comment_text}"


def _append_log(existing: Mapping[str, Any] | None, line: str) -> str:
    before = str(_scalar((existing or {}).get("分数变化日志")) or "").strip()
    return f"{before}\n{line}" if before else line


def build_schoology_write_plan(
    snapshot: Mapping[str, Any],
    *,
    student_uid: str,
    student_term_id: str,
    course_task_records: Iterable[Mapping[str, Any]],
    student_task_records: Iterable[Mapping[str, Any]],
    grade_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create deterministic write plans for the current student only.

    Plans have explicit ``record_id`` only for rows whose stable identity is
    already present in Base.  Missing links go to ``exceptions`` and must be
    resolved before an automatic write is permitted.
    """
    course_tasks = {key: row for row in course_task_records if (key := _course_task_key(row))}
    existing_tasks = {
        (_link_id(row, "任务归属学生"), _link_id(row, "所属课程任务")): row
        for row in student_task_records
        if _link_id(row, "任务归属学生") and _link_id(row, "所属课程任务")
    }
    existing_grades = {
        (str(_scalar(row.get("学生UID")) or ""), str(_scalar(row.get("SectionNID")) or ""), str(_scalar(row.get("作业NID")) or "")): row
        for row in grade_records
    }
    submissions: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for event in snapshot.get("submission_events", []):
        if str(event.get("student_uid") or "") == student_uid:
            submissions[(str(event.get("section_nid") or ""), str(event.get("schoology_id") or ""))].append(event)

    grade_item_ids = {
        str(item.get("grade_item_key") or item.get("assignment_key") or ""): str(item.get("grade_item_nid") or "")
        for item in snapshot.get("grade_items", [])
    }

    plan: dict[str, list[dict[str, Any]]] = {"student_task_updates": [], "grade_updates": [], "grade_events": [], "course_grade_observations": [], "exceptions": []}
    for (section, assignment), events in submissions.items():
        course_task = course_tasks.get((section, assignment))
        if not course_task:
            plan["exceptions"].append({"类型": "未匹配课程任务", "student_uid": student_uid, "SectionNID": section, "作业NID": assignment})
            continue
        task = existing_tasks.get((student_term_id, str(course_task["record_id"])))
        if not task:
            plan["exceptions"].append({"类型": "未匹配学生任务", "student_term_id": student_term_id, "课程任务record_id": course_task["record_id"], "SectionNID": section, "作业NID": assignment})
            continue
        ordered = sorted(events, key=lambda item: str(item.get("submitted_at") or ""))
        latest = ordered[-1]
        fields = {
            "当前提交状态": [_submission_state(str(latest.get("status") or ""))],
            "首次提交时间": ordered[0].get("submitted_at"),
            "最近提交时间": latest.get("submitted_at"),
        }
        plan["student_task_updates"].append({"record_id": task["record_id"], "fields": {key: value for key, value in fields.items() if value is not None}})

    for grade in snapshot.get("grade_records", []):
        if str(grade.get("student_uid") or "") != student_uid:
            continue
        section = str(grade.get("section_nid") or "")
        grade_key = str(grade.get("grade_item_key") or grade.get("assignment_key") or "")
        assignment = grade_item_ids.get(grade_key, "")
        if not assignment:
            plan["exceptions"].append({"类型": "成绩缺少作业稳定ID", "student_uid": student_uid, "SectionNID": section})
            continue
        course_task = course_tasks.get((section, assignment))
        if not course_task:
            plan["exceptions"].append({"类型": "成绩未匹配课程任务", "student_uid": student_uid, "SectionNID": section, "作业NID": assignment})
            continue
        task = existing_tasks.get((student_term_id, str(course_task["record_id"])))
        if not task:
            plan["exceptions"].append({"类型": "成绩未匹配学生任务", "student_term_id": student_term_id, "课程任务record_id": course_task["record_id"], "SectionNID": section, "作业NID": assignment})
            continue
        key = (student_uid, section, assignment)
        old = existing_grades.get(key)
        change = _change_log(old, grade)
        # Re-reading the same Schoology fact is intentionally a no-op.  This
        # preserves a factual change history instead of turning every crawl
        # into a fake score change.
        if not change:
            continue
        fields = {
            "学生UID": student_uid,
            "SectionNID": section,
            "作业NID": assignment,
            "所属课程任务": [{"id": str(course_task["record_id"])}],
            "学生学期任务": [{"id": str(task["record_id"])}],
            "得分": grade.get("score"),
            "满分": grade.get("max_points"),
            "老师评语": grade.get("comment_text"),
            "更新时间": grade.get("observed_at"),
            "分数变化日志": _append_log(old, change[1]),
        }
        plan["grade_updates"].append({"record_id": old.get("record_id") if old else None, "fields": {name: value for name, value in fields.items() if value is not None}})
        plan["grade_events"].append({"student_uid": student_uid, "SectionNID": section, "作业NID": assignment, "类型": change[0], "observed_at": grade.get("observed_at")})
        if grade.get("overall_course_grade") is not None:
            plan["course_grade_observations"].append({"student_term_id": student_term_id, "SectionNID": section, "overall": grade["overall_course_grade"], "observed_at": grade.get("observed_at")})
    return plan
