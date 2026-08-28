#!/usr/bin/env python3
"""Synchronise Airtable S1 enrolment into the Feishu learning Base.

The Airtable student record's OEN is the only automatic identity key.  When an
OEN selected in S1 is not yet in Feishu, this workflow creates a minimal
``学生主档`` and the configured current ``学生学期`` before writing T1/T2.

The default mode is read-only and emits a plan.  ``--apply`` performs only
additive/safe changes: creates, T1/T2/campus updates, and missing future
student-session links.  It deliberately does not delete a student term,
historical attendance, submissions, tasks, grades, or past session records.
Those are reported as retirement candidates for a separately approved process.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date
from typing import Any, Iterable
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


BASE_TABLES = {
    "学生主档": "tbl9PhF99dUkTU1A",
    "学生学期": "tblzZy2DoDWLs4LP",
    "学期场次": "tbllrHXPQrAcRfCR",
    "学生场次": "tbl7A83OXf3kQvpR",
}
CAMPUS_MAP = {"上外": "上海"}


def scalar(value: Any) -> str | None:
    if isinstance(value, list):
        return str(value[0]).strip() if len(value) == 1 and value[0] not in (None, "") else None
    return str(value).strip() if value not in (None, "") else None


def link_id(value: Any) -> str | None:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("id") or "") or None
    return None


def canonical_campus(value: Any) -> str | None:
    campus = scalar(value)
    return CAMPUS_MAP.get(campus, campus)


def parse_s1_course(value: Any) -> str | None:
    name = scalar(value)
    if not name or not name.startswith("S1-") or not name.endswith("-N"):
        return None
    return name[3:-2].strip() or None


def slot_from_period(value: Any) -> str | None:
    period = scalar(value)
    return {"T1(8-10am)": "T1", "T2(10-12noon)": "T2"}.get(period)


def append_log(existing: Any, line: str) -> str:
    prior = str(existing or "").strip()
    return f"{prior}\n{line}" if prior else line


def local_date(value: Any) -> date | None:
    text = scalar(value)
    if not text:
        return None


def start_date_value(value: Any) -> str | None:
    parsed = local_date(value)
    return f"{parsed.isoformat()} 00:00" if parsed else None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


class AirtableClient:
    def __init__(self, token: str, base_id: str):
        self.token, self.base_id = token, base_id

    def list_records(self, table_id: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        offset = None
        result: list[dict[str, Any]] = []
        while True:
            query: list[tuple[str, str]] = [("pageSize", "100")]
            query.extend(("fields[]", field) for field in fields)
            if offset:
                query.append(("offset", offset))
            url = f"https://api.airtable.com/v0/{self.base_id}/{quote(table_id, safe='')}?{urlencode(query)}"
            request = Request(url, headers={"Authorization": f"Bearer {self.token}"})
            with urlopen(request, timeout=30) as response:  # nosec B310 - fixed Airtable API endpoint
                payload = json.loads(response.read().decode("utf-8"))
            result.extend(payload.get("records", []))
            offset = payload.get("offset")
            if not offset:
                return result


class LarkBaseClient:
    def __init__(self, base_token: str, profile: str, identity: str):
        self.base_token, self.profile, self.identity = base_token, profile, identity

    def _run(self, args: list[str]) -> dict[str, Any]:
        command = ["lark-cli", "base", *args, "--as", self.identity, "--profile", self.profile, "--format", "json"]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        raw = (completed.stdout or completed.stderr).strip()
        start = raw.find("{")
        if completed.returncode or start < 0:
            raise RuntimeError(f"lark_cli_failed:{completed.returncode}:{raw[-500:]}")
        payload = json.loads(raw[start:])
        if payload.get("ok") is not True:
            raise RuntimeError(f"lark_cli_failed:{payload.get('error')}")
        return payload["data"]

    def list_records(self, table_id: str, fields: list[str], filter_json: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            args = ["+record-list", "--base-token", self.base_token, "--table-id", table_id, "--limit", "200", "--offset", str(offset)]
            for field in fields:
                args.extend(("--field-id", field))
            if filter_json:
                args.extend(("--filter-json", json.dumps(filter_json, ensure_ascii=False)))
            data = self._run(args)
            names = data.get("fields", [])
            values = data.get("data", [])
            record_ids = data.get("record_id_list", [])
            rows.extend({"record_id": record_ids[index], **dict(zip(names, row))} for index, row in enumerate(values))
            if not data.get("has_more"):
                return rows
            offset += len(values)

    def upsert(self, table_id: str, fields: dict[str, Any], record_id: str | None = None) -> dict[str, Any]:
        args = ["+record-upsert", "--base-token", self.base_token, "--table-id", table_id, "--json", json.dumps(fields, ensure_ascii=False)]
        if record_id:
            args.extend(("--record-id", record_id))
        return self._run(args)

    def batch_create(self, table_id: str, records: list[dict[str, Any]]) -> int:
        created = 0
        for index in range(0, len(records), 200):
            chunk = records[index:index + 200]
            data = self._run(["+record-batch-create", "--base-token", self.base_token, "--table-id", table_id, "--json", json.dumps({"create_records": chunk}, ensure_ascii=False)])
            count = len(data.get("record_id_list", []))
            if count != len(chunk):
                raise RuntimeError(f"unexpected_batch_create_count:{count}:{len(chunk)}")
            created += count
        return created

    def delete(self, table_id: str, record_ids: list[str]) -> int:
        deleted = 0
        for index in range(0, len(record_ids), 200):
            chunk = record_ids[index:index + 200]
            self._run(["+record-delete", "--base-token", self.base_token, "--table-id", table_id,
                       "--json", json.dumps({"record_id_list": chunk}), "--yes"])
            deleted += len(chunk)
        return deleted


def build_roster_profiles(*, airtable_students: list[dict[str, Any]], name_field: str, oen_field: str, campus_field: str) -> dict[str, dict[str, Any]]:
    students = {}
    for row in airtable_students:
        fields = row.get("fields", {})
        oen = scalar(fields.get(oen_field))
        if oen:
            name = scalar(fields.get(name_field)) or ""
            students[row["id"]] = {
                "name": name,
                "pinyin": name,
                "oen": oen,
                "campus": canonical_campus(fields.get(campus_field)),
                "email": scalar(fields.get("Email")),
                "start_date": start_date_value(fields.get("Starting Date")),
            }
    return {profile["oen"]: profile for profile in students.values()}


def build_source_enrolment(*, airtable_students: list[dict[str, Any]], s1_rows: list[dict[str, Any]], name_field: str, oen_field: str, campus_field: str, s1_name_field: str, s1_students_field: str, period_field: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    students_by_oen = build_roster_profiles(airtable_students=airtable_students, name_field=name_field, oen_field=oen_field, campus_field=campus_field)
    students = {row["id"]: students_by_oen.get(scalar(row.get("fields", {}).get(oen_field))) for row in airtable_students}
    exceptions: list[dict[str, Any]] = []
    enrolment: dict[str, dict[str, Any]] = {}
    for row in s1_rows:
        fields = row.get("fields", {})
        course, slot = parse_s1_course(fields.get(s1_name_field)), slot_from_period(fields.get(period_field))
        if not course or not slot:
            continue
        for student_id in fields.get(s1_students_field, []) or []:
            student = students.get(student_id)
            if not student:
                exceptions.append({"类型": "S1学生缺少OEN或学生名册记录", "airtable_student_record_id": student_id, "课程": course, "时段": slot})
                continue
            current = enrolment.setdefault(student["oen"], {**student, "T1": None, "T2": None})
            if current[slot] and current[slot] != course:
                exceptions.append({"类型": "同一学生同一时段多门课程", "OEN": student["oen"], "原课程": current[slot], "冲突课程": course, "时段": slot})
            else:
                current[slot] = course
    return enrolment, exceptions


def session_candidates(term: dict[str, Any], term_sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for session in term_sessions:
        if link_id(session.get("学期")) != term["semester_id"]:
            continue
        course = scalar(session.get("课程编码"))
        slot = "T1" if course == term.get("T1") else "T2" if course == term.get("T2") else None
        if not slot:
            continue
        coverage = scalar(session.get("教学覆盖学生"))
        group = term.get(f"{slot}分组")
        if coverage != "大班课" and coverage != group:
            continue
        result.append(session)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="默认仅输出计划；传入后才写飞书")
    parser.add_argument("--base-token", default=os.getenv("FEISHU_BASE_TOKEN", "GSFqbOVH9awprdsGlMLcjhAhnje"))
    parser.add_argument("--semester-record-id", default=os.getenv("FEISHU_SEMESTER_RECORD_ID"), required=not bool(os.getenv("FEISHU_SEMESTER_RECORD_ID")))
    parser.add_argument("--airtable-base-id", default=os.getenv("AIRTABLE_BASE_ID", "app0bWMb7eh9q5eoz"))
    parser.add_argument("--airtable-student-table-id", default=os.getenv("AIRTABLE_STUDENT_TABLE_ID", "tblJXvnYQSHouSlIF"))
    parser.add_argument("--airtable-s1-table-id", default=os.getenv("AIRTABLE_S1_TABLE_ID", "tblNPDd714aDtHcOl"))
    parser.add_argument("--profile", default=os.getenv("LARK_PROFILE", "source-school"))
    parser.add_argument("--identity", choices=("user", "bot"), default=os.getenv("LARK_IDENTITY", "user"))
    args = parser.parse_args()
    airtable_token = os.getenv("AIRTABLE_TOKEN", "").strip()
    if not airtable_token:
        parser.error("缺少 AIRTABLE_TOKEN")

    source = AirtableClient(airtable_token, args.airtable_base_id)
    lark = LarkBaseClient(args.base_token, args.profile, args.identity)
    name_field, oen_field, campus_field = "Names ONLY", "OEN", "Campus"
    s1_name, s1_students, s1_period = "Name", "Student Name", "Period (bejing)"
    print("[预演] 正在读取 Airtable 学生名册…", file=sys.stderr, flush=True)
    airtable_students = source.list_records(args.airtable_student_table_id, (name_field, oen_field, campus_field, "Email", "Starting Date"))
    print("[预演] 正在读取 Airtable S1 选课…", file=sys.stderr, flush=True)
    s1_rows = source.list_records(args.airtable_s1_table_id, (s1_name, s1_students, s1_period))
    roster_profiles = build_roster_profiles(airtable_students=airtable_students, name_field=name_field, oen_field=oen_field, campus_field=campus_field)
    enrolment, exceptions = build_source_enrolment(
        airtable_students=airtable_students,
        s1_rows=s1_rows,
        name_field=name_field, oen_field=oen_field, campus_field=campus_field,
        s1_name_field=s1_name, s1_students_field=s1_students, period_field=s1_period,
    )
    print("[预演] 正在读取飞书学生主档…", file=sys.stderr, flush=True)
    masters = lark.list_records(BASE_TABLES["学生主档"], ["学生姓名", "OEN", "拼音", "邮箱", "开始日期"])
    masters_by_oen = {scalar(row.get("OEN")): row for row in masters if scalar(row.get("OEN"))}
    new_oens = sorted(set(enrolment) - set(masters_by_oen))
    if args.apply:
        for oen in new_oens:
            person = enrolment[oen]
            fields = {"学生姓名": person["name"], "OEN": oen}
            for source_key, target_key in (("pinyin", "拼音"), ("email", "邮箱"), ("start_date", "开始日期")):
                if person.get(source_key):
                    fields[target_key] = person[source_key]
            lark.upsert(BASE_TABLES["学生主档"], fields)
        if new_oens:
            masters = lark.list_records(BASE_TABLES["学生主档"], ["学生姓名", "OEN", "拼音", "邮箱", "开始日期"])
            masters_by_oen = {scalar(row.get("OEN")): row for row in masters if scalar(row.get("OEN"))}

    profile_updates = []
    for oen, person in roster_profiles.items():
        master = masters_by_oen.get(oen)
        if not master:
            continue
        fields = {}
        for source_key, target_key in (("pinyin", "拼音"), ("email", "邮箱"), ("start_date", "开始日期")):
            # Profile details may have manual corrections in Feishu.  This
            # workflow backfills blank values only; it never clears or replaces
            # an existing Feishu value from the Airtable roster.
            if person.get(source_key) and not scalar(master.get(target_key)):
                fields[target_key] = person[source_key]
        if fields:
            profile_updates.append({"record_id": master["record_id"], "fields": fields})
    if args.apply:
        for item in profile_updates:
            lark.upsert(BASE_TABLES["学生主档"], item["fields"], item["record_id"])

    print("[预演] 正在读取飞书学生学期…", file=sys.stderr, flush=True)
    terms = lark.list_records(BASE_TABLES["学生学期"], ["学生姓名", "学年学期", "校区", "T1", "T2", "T1分组", "T2分组", "追踪日志"])
    term_by_master = {}
    for term in terms:
        if link_id(term.get("学年学期")) == args.semester_record_id and link_id(term.get("学生姓名")):
            term_by_master[link_id(term["学生姓名"])] = term
    term_creates, term_updates, retirements = [], [], []
    pending_terms_after_master_create: list[dict[str, Any]] = []
    today = date.today()
    for oen, person in enrolment.items():
        master = masters_by_oen.get(oen)
        if not master:
            # In a dry run, a source-only OEN is expected: --apply first
            # creates the master and then creates its term record.  Report it
            # as a planned chain, not an error.
            if not args.apply and oen in new_oens:
                pending_terms_after_master_create.append({"OEN": oen, "学生姓名": person["name"]})
                continue
            exceptions.append({"类型": "主档创建后仍无法定位", "OEN": oen})
            continue
        current = term_by_master.get(master["record_id"])
        desired = {"校区": [person["campus"]] if person.get("campus") else None, "T1": [person["T1"]] if person.get("T1") else None, "T2": [person["T2"]] if person.get("T2") else None}
        if not current:
            fields = {
                "学生姓名": [{"id": master["record_id"]}],
                "学年学期": [{"id": args.semester_record_id}],
                **{key: value for key, value in desired.items() if value},
            }
            term_creates.append({"OEN": oen, "fields": fields})
            continue
        changes = {key: value for key, value in desired.items() if (scalar(current.get(key)) != scalar(value))}
        if changes:
            changes["追踪日志"] = append_log(current.get("追踪日志"), f"{today.isoformat()}｜Airtable S1选课同步｜校区/T1/T2按来源更新")
            term_updates.append({
                "OEN": oen,
                "record_id": current["record_id"],
                "fields": changes,
                "旧课程": {course for course in (scalar(current.get("T1")), scalar(current.get("T2"))) if course},
            })
    active_master_ids = {row["record_id"] for row in masters_by_oen.values()}
    source_oens = set(enrolment)
    for term in terms:
        master_id = link_id(term.get("学生姓名"))
        master = next((row for row in masters_by_oen.values() if row["record_id"] == master_id), None)
        if link_id(term.get("学年学期")) == args.semester_record_id and master and scalar(master.get("OEN")) not in source_oens:
            retirements.append({"student_term_id": term["record_id"], "类型": "Airtable S1无选课来源，需按未来场次保留规则处理"})

    if args.apply:
        for item in term_creates:
            lark.upsert(BASE_TABLES["学生学期"], item["fields"])
        for item in term_updates:
            lark.upsert(BASE_TABLES["学生学期"], item["fields"], item["record_id"])
        terms = lark.list_records(BASE_TABLES["学生学期"], ["学生姓名", "学年学期", "校区", "T1", "T2", "T1分组", "T2分组"])
        term_by_master = {link_id(term.get("学生姓名")): term for term in terms if link_id(term.get("学年学期")) == args.semester_record_id}

    # Reconcile only student records whose S1 selection changed.  Existing
    # sessions are never inferred away: only links to a previous course, with
    # a verified future date, are eligible for removal.
    session_creates: list[dict[str, Any]] = []
    future_session_deletes: list[str] = []
    session_target_oens = {item["OEN"] for item in term_creates + term_updates}
    if session_target_oens and (args.apply or term_updates):
        print("[预演] 正在核对受影响学生的未来场次…", file=sys.stderr, flush=True)
        term_sessions = lark.list_records(BASE_TABLES["学期场次"], ["学期", "课程编码", "教学覆盖学生", "上课日期"])
        session_by_id = {row["record_id"]: row for row in term_sessions}
        old_courses_by_oen = {item["OEN"]: item.get("旧课程", set()) for item in term_updates}
        updates_by_oen = {item["OEN"]: item for item in term_updates}
        for oen in session_target_oens:
            master = masters_by_oen.get(oen)
            term = term_by_master.get(master["record_id"]) if master else None
            if not term:
                # Dry runs cannot get a record ID for a master that will only
                # exist after apply. Its sessions are reported as post-create.
                continue
            effective_term = dict(term)
            # --apply has already re-read the updated record.  During dry-run,
            # merge the planned T1/T2/campus update so session reconciliation
            # previews the destination schedule rather than the old one.
            if not args.apply and oen in updates_by_oen:
                effective_term.update(updates_by_oen[oen]["fields"])
            planned = session_candidates({"semester_id": args.semester_record_id, "T1": scalar(effective_term.get("T1")), "T2": scalar(effective_term.get("T2")), "T1分组": scalar(effective_term.get("T1分组")), "T2分组": scalar(effective_term.get("T2分组"))}, term_sessions)
            planned_ids = {row["record_id"] for row in planned}
            existing = lark.list_records(BASE_TABLES["学生场次"], ["学生学期", "学期场次", "上课日期"], {"logic": "and", "conditions": [["学生学期", "intersects", [{"id": term["record_id"]}]]]})
            existing_ids = {link_id(row.get("学期场次")) for row in existing}
            for session in planned:
                if session["record_id"] not in existing_ids:
                    session_creates.append({"学生场次唯一键": f"{term['record_id']}|{session['record_id']}", "学生学期": [{"id": term["record_id"]}], "学期场次": [{"id": session["record_id"]}]})
            for student_session in existing:
                linked_id = link_id(student_session.get("学期场次"))
                upstream = session_by_id.get(linked_id or "")
                course = scalar(upstream.get("课程编码")) if upstream else None
                occurs_on = local_date(student_session.get("上课日期")) or (local_date(upstream.get("上课日期")) if upstream else None)
                if (linked_id not in planned_ids and course in old_courses_by_oen.get(oen, set())
                        and occurs_on and occurs_on > today):
                    future_session_deletes.append(student_session["record_id"])
        if args.apply:
            # Deleting only the precomputed future links first avoids a student
            # appearing in both old and new courses after a schedule change.
            deleted_sessions = lark.delete(BASE_TABLES["学生场次"], future_session_deletes) if future_session_deletes else 0
            created_sessions = lark.batch_create(BASE_TABLES["学生场次"], session_creates) if session_creates else 0
        else:
            deleted_sessions = 0
            created_sessions = 0
    else:
        deleted_sessions = 0
        created_sessions = 0

    plan = {
        "dry_run": not args.apply,
        "来源选课学生": len(enrolment),
        "来源学生主档资料": len(roster_profiles),
        "待建学生主档": [{"OEN": oen, "学生姓名": enrolment[oen]["name"], "校区": enrolment[oen].get("campus")} for oen in new_oens],
        "新增学生主档": len(new_oens),
        "待补全学生主档资料": len(profile_updates),
        "新增学生学期": len(term_creates) + len(pending_terms_after_master_create),
        "更新学生学期": len(term_updates),
        "待删除未来学生场次": deleted_sessions if args.apply else len(future_session_deletes),
        "待新增未来学生场次": created_sessions if args.apply else len(session_creates),
        "退课候选": retirements,
        "异常": exceptions,
    }
    print(json.dumps(plan, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
