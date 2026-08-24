"""Build a workflow input from reviewed Feishu Base exports.

This is deliberately a pure adapter: callers export only the records required
for one ``学生学期 + 教学周`` and the adapter makes no network call or write.
It does not turn AI candidates into facts.  In particular, classroom
interaction enters the parent report only when ``互动情况 == 已确认``.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def _text(record: Mapping[str, Any], field: str) -> str:
    return str(_scalar(record.get(field)) or "").strip()


def _date(record: Mapping[str, Any], field: str) -> str:
    return _text(record, field)[:10]


def _link_id(record: Mapping[str, Any], field: str) -> str | None:
    links = record.get(field) or []
    if len(links) == 1 and isinstance(links[0], Mapping) and links[0].get("id"):
        return str(links[0]["id"])
    return None


def _week_number(value: str | int) -> int:
    raw = str(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError("invalid_teaching_week")
    return int(digits)


def _task_name(record: Mapping[str, Any]) -> str:
    return _text(record, "任务标题") or _text(record, "作业名称") or _text(record, "所属课程任务") or "未命名任务"


def build_weekly_feedback_input(
    *,
    student_term: Mapping[str, Any],
    student_name: str,
    week_label: str | int,
    week_start: str,
    week_end: str,
    as_of: str,
    student_sessions: Iterable[Mapping[str, Any]],
    term_sessions: Iterable[Mapping[str, Any]],
    student_tasks: Iterable[Mapping[str, Any]],
    grade_records: Iterable[Mapping[str, Any]],
    report_term: str = "",
    educator: str = "",
) -> dict[str, Any]:
    """Construct the V1 workflow input without inventing missing facts."""
    student_sessions = list(student_sessions)
    term_sessions = list(term_sessions)
    student_tasks = list(student_tasks)
    grade_records = list(grade_records)
    start, end = date.fromisoformat(week_start), date.fromisoformat(week_end)
    student_term_id = str(student_term.get("record_id") or "")
    if not student_term_id:
        raise ValueError("missing_student_term_record_id")
    term_by_id = {str(row.get("record_id")): row for row in term_sessions if row.get("record_id")}
    selected_sessions = [
        row for row in student_sessions
        if _link_id(row, "学生学期") == student_term_id and start <= date.fromisoformat(_date(row, "上课日期")) <= end
    ]
    if not selected_sessions:
        raise ValueError("no_student_sessions_in_week")
    linked_session_ids = {_link_id(row, "学期场次") for row in selected_sessions}
    linked_session_ids.discard(None)
    missing = linked_session_ids - set(term_by_id)
    if missing:
        raise ValueError("missing_linked_term_sessions")
    week_term_sessions = sorted(
        (term_by_id[record_id] for record_id in linked_session_ids),
        key=lambda row: (_date(row, "上课日期"), _text(row, "时间"), str(row.get("record_id") or "")),
    )

    sessions, confirmations = [], []
    for row in week_term_sessions:
        source = _text(row, "课程内容总结")
        status = _text(row, "内容确认状态")
        record_id = str(row["record_id"])
        # Unconfirmed content is deliberately passed as no source: it becomes
        # a visible workflow gap rather than a plausible-looking summary.
        sessions.append({"session_id": record_id, "course_code": _text(row, "课程编码"), "source_text": source if status == "已确认" else ""})
        if status == "已确认":
            confirmations.append({"session_id": record_id, "status": "已确认", "confirmed_by": _text(row, "内容确认人"), "confirmed_at": _text(row, "内容确认时间")})

    content_by_course: dict[str, list[str]] = defaultdict(list)
    for row in week_term_sessions:
        if _text(row, "内容确认状态") == "已确认" and _text(row, "课程内容总结"):
            content_by_course[_text(row, "课程编码")].append(_text(row, "课程内容总结"))
    interaction_by_course: dict[str, list[str]] = defaultdict(list)
    for row in selected_sessions:
        if _text(row, "互动情况") == "已确认" and _text(row, "互动内容"):
            term = term_by_id[_link_id(row, "学期场次") or ""]
            interaction_by_course[_text(term, "课程编码")].append(_text(row, "互动内容"))
    report_courses = []
    for course, contents in sorted(content_by_course.items()):
        interactions = interaction_by_course.get(course, [])
        report_courses.append({
            "code": course,
            "title": course,
            "session_count": sum(_text(row, "课程编码") == course for row in week_term_sessions),
            "session_summary": f"本周{sum(_text(row, '课程编码') == course for row in week_term_sessions)}场已确认课程",
            "actual_content": "\n\n".join(dict.fromkeys(contents)),
            "actual_content_confirmed": True,
            "confirmed_interaction": "\n".join(dict.fromkeys(interactions)),
            "interaction_confirmation_status": "已确认" if interactions else "待确认",
        })

    task_rows = []
    for row in student_tasks:
        if _link_id(row, "任务归属学生") != student_term_id:
            continue
        task_rows.append({
            "task_id": str(row.get("record_id") or ""), "课程": _text(row, "课程"), "所属模块": _text(row, "所属模块"),
            "任务名称": _task_name(row), "原始Deadline": _date(row, "截止日期"), "补做Deadline": _date(row, "补做Deadline"),
            "返工Deadline": _date(row, "返工Deadline"), "当前提交状态": _text(row, "当前提交状态") or "未提交",
            "检查状态": _text(row, "检查状态") or "待确认", "教师反馈": _text(row, "老师评语"),
        })
    target_task_ids = {str(row.get("record_id")) for row in student_tasks if _link_id(row, "任务归属学生") == student_term_id and row.get("record_id")}
    grade_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in grade_records:
        # Grade rows are only reportable when their student-task Link proves
        # they belong to this student term.  A score with no such link is an
        # orphan fact and must not appear in another student's feedback.
        if _link_id(row, "学生学期任务") not in target_task_ids:
            continue
        score, maximum = _scalar(row.get("得分")), _scalar(row.get("满分"))
        if score is None or maximum in (None, 0, "", "0"):
            continue
        course = _text(row, "课程") or "未标注课程"
        grade_series[course].append({"label": _text(row, "作业名") or "已评分任务", "score": round(float(score) / float(maximum) * 100, 2)})
    return {
        "course": {"course_offering_id": f"student-term:{student_term_id}", "course_code": "多课程"},
        "week": {"number": _week_number(week_label), "start": week_start, "end": week_end},
        "student": {"id": student_term_id, "student_term_id": student_term_id, "name": student_name, "aliases": [student_name]},
        "report": {"title": f"{student_name}第{_week_number(week_label)}周学习反馈", "term": report_term, "educator": educator, "version_label": "草稿"},
        "base_attendance": {"student_session_records": list(student_sessions), "term_session_records": list(term_sessions), "as_of": as_of},
        "sessions": sessions,
        "human_confirmations": confirmations,
        "report_courses": report_courses,
        "tasks": task_rows,
        "grades": [], "prior_grades": [],
        "grade_series": [{"course_code": course, "points": points} for course, points in sorted(grade_series.items())],
        "ielts_report": {}, "pbl_report": {}, "confirmed_next_actions": [], "pbl_evidence": [],
        "publication": {"approved_by_educator": False},
    }
