"""Deterministic Base records -> weekly attendance payload adapter.

This module only organizes Base facts.  It does not decide formal attendance,
excused/unexcused status, cancellations, rescheduling, or an attendance rate.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping


ONLINE_CAMPUSES = frozenset({"线上", "线上校区"})
OFFLINE_CAMPUSES = frozenset({"北京", "苏州", "重庆巴渝", "上海", "广州", "深圳", "重庆西大"})
# The upstream table uses “重庆光环” for the student-facing “重庆西大” campus.
# This is a field-name mapping only; it does not infer a campus assignment.
UPSTREAM_CAMPUS_FIELDS = {
    "北京": "北京",
    "苏州": "苏州",
    "重庆巴渝": "重庆巴渝",
    "重庆西大": "重庆光环",
    "上海": "上海",
    "广州": "广州",
    "深圳": "深圳",
}
RECORDED_STATUSES = frozenset({"出勤", "缺勤", "请假", "迟到", "早退", "无需出勤"})
OBSERVED_PARTICIPATION_STATUSES = frozenset({"出勤", "迟到", "早退"})
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class AttendanceAdapterError(ValueError):
    """Raised when Base facts cannot be mapped without guessing."""


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        if not value:
            return None
        if len(value) == 1:
            return value[0]
        raise AttendanceAdapterError(f"expected_single_value:{value!r}")
    return value


def _linked_id(record: Mapping[str, Any], field: str) -> str | None:
    links = record.get(field) or []
    if len(links) != 1 or not isinstance(links[0], Mapping) or not links[0].get("id"):
        return None
    return str(links[0]["id"])


def _local_date(value: Any, field: str) -> date:
    raw = _scalar(value)
    if not raw:
        raise AttendanceAdapterError(f"missing_{field}")
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as error:
        raise AttendanceAdapterError(f"invalid_{field}:{raw}") from error


def _scope_for_campus(campus: str) -> str:
    if campus in ONLINE_CAMPUSES:
        return "线上"
    if campus in OFFLINE_CAMPUSES:
        return "线下"
    raise AttendanceAdapterError(f"unknown_campus_scope:{campus or 'empty'}")


def _slot_sort(value: str) -> tuple[str, str]:
    return (value.split("-", 1)[0].strip().zfill(5), value)


def _display_text(scope: str, status: str | None, camera: str | None, classroom: str | None, fact_status: str) -> str:
    if fact_status == "future":
        return "未来场次 · 出勤尚未发生"
    if fact_status == "unrecorded":
        text = f"{scope}出勤：暂无记录"
    else:
        text = f"{scope}出勤：{status}"
        if scope == "线下" and classroom:
            text += f" · {classroom}"
    return text + (f" · 摄像头：{camera}" if camera else " · 摄像头状态暂无记录")


def _missing_support_slot_diagnostics(
    *,
    campus: str,
    selected: list[tuple[date, Mapping[str, Any], Mapping[str, Any]]],
    term_session_records: Iterable[Mapping[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Report an observed upstream/student-record gap without inventing a session.

    The 12:30 智育辅导 slot is deliberately treated as a diagnostic focus because
    it is the slot under investigation.  A diagnostic is emitted only when the
    upstream has rows in the requested week and this student's campus has no
    corresponding student-session rows.  It never adds a row to ``sessions``.
    """
    upstream_rows = []
    for record in term_session_records:
        session_date = _local_date(record.get("上课日期"), "上课日期")
        slot = str(_scalar(record.get("时间")) or "").strip()
        category = str(_scalar(record.get("场次类别")) or "").strip()
        if start <= session_date <= end and slot == "12:30-13:00" and category == "智育辅导":
            upstream_rows.append((session_date, record))
    if not upstream_rows:
        return []

    student_rows = [
        (session_date, record, term_record)
        for session_date, record, term_record in selected
        if str(_scalar(record.get("时间")) or "").strip() == "12:30-13:00"
        and str(_scalar(record.get("场次类别")) or "").strip() == "智育辅导"
    ]
    if student_rows:
        return []

    upstream_field = UPSTREAM_CAMPUS_FIELDS.get(campus)
    if upstream_field is None:
        return []
    # A missing key means the caller did not project the campus field.  It is
    # not evidence that the Base cell itself is empty, so do not emit a false
    # "unassigned" diagnosis.
    if any(upstream_field not in record for _, record in upstream_rows):
        return []
    assigned_rows = [record for _, record in upstream_rows if _scalar(record.get(upstream_field)) not in (None, "")]
    if assigned_rows:
        status = "upstream_assigned_but_student_relation_missing"
        message = "上游该时段已有校区字段值，但本学生没有对应学生场次记录；不据此推断应参加或补造场次。"
    else:
        status = "upstream_campus_unassigned"
        message = "上游存在该时段，但目标校区字段为空；本学生没有对应学生场次记录，因此不生成透视格。"
    return [{
        "type": "missing_student_session_records",
        "status": status,
        "校区": campus,
        "时间": "12:30-13:00",
        "场次类别": "智育辅导",
        "学期场次记录数": len(upstream_rows),
        "学生场次记录数": len(student_rows),
        "上游校区字段": upstream_field,
        "上游校区字段有值记录数": len(assigned_rows),
        "学期场次record_id": [str(record["record_id"]) for _, record in upstream_rows],
        "message": message,
    }]


def build_weekly_attendance_payload(
    student_session_records: Iterable[Mapping[str, Any]],
    term_session_records: Iterable[Mapping[str, Any]],
    *,
    student_term_id: str,
    week_start: str | date,
    week_end: str | date,
    as_of: str | date,
) -> dict[str, Any]:
    """Build one anonymous student's weekly pivot and cell-level audit trail.

    A Base row proves a student-session relationship, but the current schema has
    no explicit should-attend, cancellation, or reschedule field.  Therefore the
    adapter reports relationship counts and leaves the formal denominator unset.
    """
    start = date.fromisoformat(week_start) if isinstance(week_start, str) else week_start
    end = date.fromisoformat(week_end) if isinstance(week_end, str) else week_end
    cutoff = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    if end < start:
        raise AttendanceAdapterError("week_end_before_start")

    term_session_records = list(term_session_records)
    upstream = {str(record["record_id"]): record for record in term_session_records}
    selected: list[tuple[date, Mapping[str, Any], Mapping[str, Any]]] = []
    for record in student_session_records:
        if _linked_id(record, "学生学期") != student_term_id:
            continue
        session_date = _local_date(record.get("上课日期"), "上课日期")
        if not start <= session_date <= end:
            continue
        term_id = _linked_id(record, "学期场次")
        term_record = upstream.get(term_id or "")
        if term_record is None:
            raise AttendanceAdapterError(f"missing_term_session:{record.get('record_id')}:{term_id}")
        for field in ("上课日期", "时间", "课程编码", "场次类别"):
            student_value = _scalar(record.get(field))
            term_value = _scalar(term_record.get(field))
            if student_value != term_value:
                raise AttendanceAdapterError(
                    f"upstream_mismatch:{record.get('record_id')}:{term_id}:{field}:{student_value!r}:{term_value!r}"
                )
        selected.append((session_date, record, term_record))

    if not selected:
        raise AttendanceAdapterError("no_student_sessions_in_week")
    unique_keys = [record.get("学生场次唯一键") for _, record, _ in selected]
    if any(not key for key in unique_keys):
        raise AttendanceAdapterError("missing_student_session_key")
    if len(set(unique_keys)) != len(unique_keys):
        raise AttendanceAdapterError("duplicate_student_session_key")
    campuses = {_scalar(record.get("学生校区")) for _, record, _ in selected}
    if len(campuses) != 1 or None in campuses:
        raise AttendanceAdapterError(f"inconsistent_student_campus:{sorted(str(x) for x in campuses)}")
    campus = str(next(iter(campuses)))
    scope = _scope_for_campus(campus)

    day_values = sorted({session_date for session_date, _, _ in selected})
    day_key = {value: value.isoformat() for value in day_values}
    days = [
        {"key": day_key[value], "label": WEEKDAY_LABELS[value.weekday()], "date": value.strftime("%m/%d")}
        for value in day_values
    ]
    slot_values = sorted(
        {str(_scalar(record.get("时间"))).strip() for _, record, _ in selected},
        key=_slot_sort,
    )

    sessions: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    recorded_count = observed_count = unrecorded_count = future_count = 0
    for session_date, record, term_record in sorted(
        selected,
        key=lambda row: (row[0], _slot_sort(str(_scalar(row[1].get("时间"))).strip()), str(row[1].get("record_id"))),
    ):
        status_field = "线上出勤情况" if scope == "线上" else "线下出勤情况"
        status = _scalar(record.get(status_field))
        # 校区决定读取哪一种出勤事实，不决定是否保留已有摄像头事实。
        camera = _scalar(record.get("摄像头开启状态"))
        classroom = _scalar(record.get("线下出勤教室")) if scope == "线下" else None
        if session_date > cutoff:
            fact_status = "future"
            future_count += 1
            # A future row cannot establish attendance even when a cell is prefilled.
            effective_status = None
            camera = None
            classroom = None
        elif status in (None, "", "未记录"):
            fact_status = "unrecorded"
            effective_status = None
            unrecorded_count += 1
        elif status in RECORDED_STATUSES:
            fact_status = "confirmed"
            effective_status = str(status)
            recorded_count += 1
            observed_count += int(effective_status in OBSERVED_PARTICIPATION_STATUSES)
        else:
            raise AttendanceAdapterError(f"unknown_attendance_status:{record.get('record_id')}:{status}")

        slot = str(_scalar(record.get("时间"))).strip()
        course = str(_scalar(record.get("课程编码")))
        category = str(_scalar(record.get("场次类别")))
        text = _display_text(scope, effective_status, camera, classroom, fact_status)
        session = {
            "source_record_id": str(record["record_id"]),
            "student_session_key": record.get("学生场次唯一键"),
            "term_session_record_id": str(term_record["record_id"]),
            "slot": slot,
            "day": day_key[session_date],
            "title": course,
            "场次类别": category,
            "fact_status": fact_status,
            "display_text": text,
        }
        if scope == "线上":
            session["线上出勤情况"] = effective_status
        else:
            session["线下出勤情况"] = effective_status
            session["线下出勤教室"] = classroom
        session["摄像头开启状态"] = camera
        sessions.append(session)
        audit.append({
            "base_record_id": session["source_record_id"],
            "student_session_key": session["student_session_key"],
            "term_session_record_id": session["term_session_record_id"],
            "pivot_cell": f"{session_date.isoformat()} | {slot}",
            "final_display_text": f"{course} · {category} | {text}",
            "upstream_fields_match": True,
        })

    elapsed_count = len(selected) - future_count
    diagnostics = _missing_support_slot_diagnostics(
        campus=campus,
        selected=selected,
        term_session_records=term_session_records,
        start=start,
        end=end,
    )
    return {
        "source": "feishu_base_student_session_records",
        "学生学期记录ID": student_term_id,
        "校区": campus,
        "出勤口径": scope,
        "学生场次关系数": len(selected),
        "已发生场次": elapsed_count,
        "未来场次": future_count,
        "出勤已记录场次": recorded_count,
        "观察到参与场次": observed_count,
        "出勤待记录场次": unrecorded_count,
        "应参加场次": None,
        "应参加分母状态": "待业务确认：当前Base缺少是否应参加、取消和调课状态字段",
        "状态": "学生场次事实，不计算正式Attendance%",
        "diagnostics": diagnostics,
        "days": days,
        "slots": slot_values,
        "sessions": sessions,
        "audit": audit,
    }
