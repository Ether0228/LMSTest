"""Validate manual Schoology stable-ID mappings before any Base write."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


NID = re.compile(r"^\d+$")


def build_mapping_write_plan(student_rows: Iterable[Mapping[str, Any]], task_rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    student_updates, task_updates, exceptions = [], [], []
    seen_uids, seen_tasks = set(), set()
    for row in student_rows:
        record_id, uid = str(row.get("record_id") or "").strip(), str(row.get("Schoology学生UID") or "").strip()
        if not uid:
            continue
        if not record_id or not NID.fullmatch(uid):
            exceptions.append({"类型": "学生SchoologyUID格式错误", "record_id": record_id})
            continue
        if uid in seen_uids:
            exceptions.append({"类型": "重复学生SchoologyUID", "Schoology学生UID": uid})
            continue
        seen_uids.add(uid)
        student_updates.append({"record_id": record_id, "fields": {"Schoology学生UID": uid}})
    for row in task_rows:
        record_id = str(row.get("record_id") or "").strip()
        section, assignment = str(row.get("SchoologySectionNID") or "").strip(), str(row.get("Schoology作业NID") or "").strip()
        if not section and not assignment:
            continue
        if not record_id or not NID.fullmatch(section) or not NID.fullmatch(assignment):
            exceptions.append({"类型": "课程作业SchoologyID格式错误", "record_id": record_id})
            continue
        key = (section, assignment)
        if key in seen_tasks:
            exceptions.append({"类型": "重复课程作业Schoology映射", "SchoologySectionNID": section, "Schoology作业NID": assignment})
            continue
        seen_tasks.add(key)
        task_updates.append({"record_id": record_id, "fields": {"SchoologySectionNID": section, "Schoology作业NID": assignment}})
    return {"student_updates": student_updates, "course_task_updates": task_updates, "exceptions": exceptions}
