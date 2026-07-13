"""
Repair Feishu submission records whose linked student is missing.

Rules:
  - If 学生姓名 exists in roster, write 关联学生.
  - If not in roster, create a minimal roster record and then write 关联学生.
  - Never deletes submission data.
"""

import os
import re
import requests


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing env: {name}")
    return value


def feishu_token(app_id, app_secret):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=30,
    ).json()
    if resp.get("code") != 0:
        raise RuntimeError(f"Feishu token failed: {resp}")
    return resp["tenant_access_token"]


def fetch_all_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, params=params, headers=headers, timeout=30).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"Fetch records failed table={table_id}: {resp}")
        data = resp.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


def linked_record_ids(value):
    if not value:
        return []
    if isinstance(value, list):
        ids = []
        for item in value:
            if isinstance(item, dict):
                rid = item.get("record_id") or item.get("id")
                if rid:
                    ids.append(rid)
            elif isinstance(item, str):
                ids.append(item)
        return ids
    return []


def create_roster_student(token, app_token, roster_table_id, student_name):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{roster_table_id}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    resp = requests.post(url, json={"fields": {"学生姓名": student_name}}, headers=headers, timeout=30).json()
    if resp.get("code") == 0:
        return resp.get("data", {}).get("record", {}).get("record_id")
    raise RuntimeError(f"Create roster student failed: {student_name} | {resp}")


def clean_url(url):
    if not url:
        return ""
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', str(url))
    return match.group(1) if match else str(url).strip()


def cell_link_url(value):
    if isinstance(value, dict):
        return value.get("link", "") or value.get("text", "")
    return str(value or "")


def active_semesters():
    raw = os.environ.get("ACTIVE_SEMESTERS", "").strip()
    return {part.strip() for part in raw.split(",") if part.strip()}


def current_semester_assignment_links(lib_records):
    semesters = active_semesters()
    if not semesters:
        return set()
    links = set()
    for rec in lib_records:
        fields = rec.get("fields", {})
        if str(fields.get("学期", "")).strip() not in semesters:
            continue
        link = clean_url(cell_link_url(fields.get("作业链接")))
        if link:
            links.add(link)
    return links


def batch_update_records(token, app_token, table_id, updates):
    if not updates:
        return 0
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    updated = 0
    for i in range(0, len(updates), 100):
        batch = updates[i:i + 100]
        resp = requests.post(url, json={"records": batch}, headers=headers, timeout=30).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"Batch update failed: {resp}")
        updated += len(batch)
    return updated


def main():
    app_id = required_env("FEISHU_APP_ID")
    app_secret = required_env("FEISHU_APP_SECRET")
    app_token = required_env("FEISHU_APP_TOKEN")
    submission_table_id = required_env("FEISHU_TABLE_ID")
    roster_table_id = required_env("FEISHU_ROSTER_TABLE_ID")
    lib_table_id = os.environ.get("FEISHU_LIB_TABLE_ID", "").strip()

    token = feishu_token(app_id, app_secret)
    roster_records = fetch_all_records(token, app_token, roster_table_id)
    roster_by_name = {
        str(rec.get("fields", {}).get("学生姓名", "")).strip(): rec.get("record_id")
        for rec in roster_records
        if str(rec.get("fields", {}).get("学生姓名", "")).strip()
    }

    active_links = set()
    if lib_table_id and active_semesters():
        lib_records = fetch_all_records(token, app_token, lib_table_id)
        active_links = current_semester_assignment_links(lib_records)
        print(f"scope active semester links: {len(active_links)}")

    submission_records = fetch_all_records(token, app_token, submission_table_id)
    updates = []
    created = 0
    already_linked = 0
    skipped_no_name = 0
    skipped_out_of_scope = 0
    skipped_new_students = set()
    known_uncreatable_students = set()

    for idx, rec in enumerate(submission_records, 1):
        fields = rec.get("fields", {})
        if active_links:
            sub_link = clean_url(cell_link_url(fields.get("作业链接")))
            if sub_link not in active_links:
                skipped_out_of_scope += 1
                continue
        if linked_record_ids(fields.get("关联学生")):
            already_linked += 1
            continue
        student_name = str(fields.get("学生姓名", "")).strip()
        if not student_name:
            skipped_no_name += 1
            continue
        roster_id = roster_by_name.get(student_name)
        if not roster_id:
            if student_name in known_uncreatable_students:
                skipped_new_students.add(student_name)
                continue
            try:
                roster_id = create_roster_student(token, app_token, roster_table_id, student_name)
                roster_by_name[student_name] = roster_id
                created += 1
            except RuntimeError as exc:
                known_uncreatable_students.add(student_name)
                skipped_new_students.add(student_name)
                print(f"skip new student without roster permission: {exc}")
                continue
        updates.append({"record_id": rec["record_id"], "fields": {"关联学生": [roster_id]}})
        if idx % 1000 == 0:
            print(f"scan progress: {idx}/{len(submission_records)} updates_pending={len(updates)}")

    updated = batch_update_records(token, app_token, submission_table_id, updates)
    print(
        f"repair complete: submissions={len(submission_records)} "
        f"already_linked={already_linked} updated={updated} "
        f"created_roster={created} skipped_no_name={skipped_no_name} "
        f"skipped_out_of_scope={skipped_out_of_scope}"
    )
    if skipped_new_students:
        print("new students need manual roster records:")
        for name in sorted(skipped_new_students):
            print(f"  - {name}")


if __name__ == "__main__":
    main()
