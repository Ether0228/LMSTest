"""
cleanup_lib_data.py

一次性清洗飞书作业库中的历史脏数据。

默认 dry-run，只打印将要修改的内容：
  - 规范化学期字段（如空白、重复值 "2025-S4,2025-S4"）
  - 修正被通知文案污染的作业名称
  - 为已进入 Gradebook 的作业补标 "🔥 极其重要"

显式传入 --apply 才会写回飞书。

必需环境变量:
  FEISHU_APP_ID
  FEISHU_APP_SECRET
  FEISHU_APP_TOKEN
  FEISHU_LIB_TABLE_ID
  FEISHU_GRADEBOOK_TABLE_ID
"""

import argparse
import calendar
import re
import time
from datetime import datetime

import requests


GRADEBOOK_COURSE_NAME_MAP = {
    "grade 11 physics": "SPH3U",
    "grade 12 physics": "SPH4U",
    "grade 11 chemistry": "SCH3U",
    "grade 12 chemistry": "SCH4U",
    "grade 11 computer science": "ICS3U",
    "grade 12 data management": "MDM4U",
    "grade 12 advanced functions": "MHF4U",
    "grade 11 functions": "MCR3U",
    "grade 12 calculus & vectors": "MCV4U",
    "grade 12 english": "ENG4U",
    "grade 11 english": "ENG3U",
    "grade 11 food and culture": "HFC3M",
    "grade 12 nutrition & health": "HFA4U",
    "grade 11 visual arts": "AVI3M",
    "grade 12 visual arts": "AVI4M",
    "grade 12 fashion": "HNB4M",
    "g10 canadian history since wwi": "CHC2D",
    "grade 12 canadian and world issues": "CGW4U",
    "grade 12 business leadership": "BOH4M",
    "g12 analysing current economic issues": "CIA4U",
    "esl level 5": "ESLEO",
    "esl level 4": "ESLDO",
    "esl level 3": "ESLCO",
    "esl level 2": "ESLBO",
}


def get_env_config():
    import os

    keys = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN",
        "FEISHU_LIB_TABLE_ID",
        "FEISHU_GRADEBOOK_TABLE_ID",
    ]
    cfg = {k: os.environ.get(k, "").strip() for k in keys}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise ValueError(f"缺少环境变量: {', '.join(missing)}")
    return cfg


def get_feishu_token(cfg):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": cfg["FEISHU_APP_ID"], "app_secret": cfg["FEISHU_APP_SECRET"]},
        timeout=30,
    ).json()
    if resp.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {resp}")
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
        resp = requests.get(url, headers=headers, params=params, timeout=30).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"拉取表失败 table={table_id}: {resp}")
        data = resp.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


def batch_update_records(token, app_token, table_id, records):
    if not records:
        return
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
        f"/tables/{table_id}/records/batch_update"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = requests.post(url, headers=headers, json={"records": batch}, timeout=30).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"批量更新失败: {resp}")
        time.sleep(0.2)


def normalize_link(value):
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    return str(value or "").strip()


def clean_schoology_url(url):
    text = normalize_link(url)
    if not text:
        return ""
    match = re.search(r"(https://.*?/(?:assignment|assessment|discussion)/\d+)", text)
    return match.group(1) if match else text


def extract_link_nid(url):
    text = clean_schoology_url(url)
    match = re.search(r"/(?:assignment|assessment|discussion)/(\d+)", text)
    return match.group(1) if match else ""


def normalize_semester_value(raw):
    if raw is None:
        return ""
    values = raw if isinstance(raw, list) else [raw]
    cleaned = []
    seen = set()
    for value in values:
        parts = re.split(r"[,\n]+", str(value or ""))
        for part in parts:
            semester = part.strip()
            if not semester:
                continue
            match = re.search(r"\d{4}-S\d+", semester, re.IGNORECASE)
            semester = match.group(0).upper() if match else semester
            if semester not in seen:
                seen.add(semester)
                cleaned.append(semester)
    return cleaned[0] if cleaned else ""


def has_duplicate_semester_value(raw):
    text = str(raw or "").strip()
    if not text or "," not in text:
        return False
    parts = [p.strip().upper() for p in text.split(",") if p.strip()]
    return len(parts) > 1 and len(set(parts)) == 1


def normalize_assignment_name(raw):
    text = str(raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_course_name(raw):
    text = str(raw or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text.split(":")[0].strip().lower())
    return GRADEBOOK_COURSE_NAME_MAP.get(normalized, text.strip())


def parse_due_date_ms(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%b %d, %Y at %I:%M %p")
    except ValueError:
        return None
    return calendar.timegm(dt.timetuple()) * 1000


def extract_assignment_name_from_notification(raw):
    text = str(raw or "").strip()
    if not text:
        return ""
    patterns = [
        r"^(.*?) (submitted|resubmitted) an item to (.*)$",
        r"^(.*?) (submitted|resubmitted) the test/quiz for (.*)$",
        r"^(.*?) (submitted|resubmitted) the assessment for (.*)$",
        r"^(.*?) (submitted|resubmitted) the discussion for (.*)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(3).strip()
    generic = re.search(
        r"^(.*?) (submitted|resubmitted) (?:the )?.*? (?:to|for) (.*)$",
        text,
        re.IGNORECASE,
    )
    return generic.group(3).strip() if generic else ""


def looks_like_notification_name(raw):
    text = str(raw or "").strip().lower()
    return " submitted " in text or " resubmitted " in text


def build_gradebook_index(rows):
    by_nid = {}
    by_name_course_sem = {}
    by_name_course = {}
    seen_name_course = set()
    seen_name_course_sem = set()

    for row in rows:
        fields = row.get("fields", {})
        nid = str(fields.get("作业NID", "")).strip()
        assignment_name = str(fields.get("作业名", "")).strip()
        course_name = normalize_course_name(fields.get("课程名", ""))
        semester = normalize_semester_value(fields.get("学期", ""))
        due_ms = parse_due_date_ms(fields.get("截止日期", ""))

        if not assignment_name or not course_name:
            continue

        meta = {
            "assignment_name": assignment_name,
            "normalized_name": normalize_assignment_name(assignment_name),
            "course_name": course_name,
            "semester": semester,
            "due_ms": due_ms,
        }

        if nid and nid not in by_nid:
            by_nid[nid] = meta

        key_course = (meta["normalized_name"], course_name)
        by_name_course.setdefault(key_course, [])
        course_signature = (key_course, nid, semester, due_ms)
        if course_signature not in seen_name_course:
            seen_name_course.add(course_signature)
            by_name_course[key_course].append(meta)

        if semester:
            key_course_sem = (meta["normalized_name"], course_name, semester)
            by_name_course_sem.setdefault(key_course_sem, [])
            course_sem_signature = (key_course_sem, nid, due_ms)
            if course_sem_signature not in seen_name_course_sem:
                seen_name_course_sem.add(course_sem_signature)
                by_name_course_sem[key_course_sem].append(meta)

    return by_nid, by_name_course_sem, by_name_course


def choose_unique_candidate(candidates):
    if len(candidates) != 1:
        return None
    return candidates[0]


def plan_lib_updates(lib_records, gradebook_rows):
    gb_by_nid, gb_by_name_course_sem, gb_by_name_course = build_gradebook_index(gradebook_rows)

    updates = []
    stats = {
        "semester_fixed": 0,
        "name_fixed": 0,
        "hot_fixed": 0,
        "due_backfilled": 0,
        "fallback_matched": 0,
        "ambiguous_skipped": 0,
        "mismatch_skipped": 0,
    }

    for rec in lib_records:
        rec_id = rec.get("record_id", "")
        fields = rec.get("fields", {})
        raw_name = str(fields.get("作业名称", "")).strip()
        raw_semester = fields.get("学期", "")
        normalized_semester = normalize_semester_value(raw_semester)
        course_name = normalize_course_name(fields.get("所属课程", ""))
        nature = str(fields.get("作业性质", "")).strip()
        clean_link = clean_schoology_url(fields.get("作业链接", ""))
        link_nid = extract_link_nid(clean_link)
        due_value = fields.get("截止日期")
        has_due = due_value not in ("", None, [])

        patch = {}
        reasons = []
        semester_changed = False

        repaired_name = extract_assignment_name_from_notification(raw_name) if looks_like_notification_name(raw_name) else ""
        target_name = repaired_name or raw_name
        normalized_target_name = normalize_assignment_name(target_name)

        if repaired_name and repaired_name != raw_name:
            patch["作业名称"] = repaired_name
            reasons.append(f"作业名称: {raw_name} -> {repaired_name}")
            stats["name_fixed"] += 1

        gb_meta = gb_by_nid.get(link_nid)
        if gb_meta is None and normalized_target_name and course_name:
            candidates = []
            if normalized_semester:
                candidates = gb_by_name_course_sem.get(
                    (normalized_target_name, course_name, normalized_semester),
                    [],
                )
            if not candidates:
                candidates = gb_by_name_course.get((normalized_target_name, course_name), [])

            unique = choose_unique_candidate(candidates)
            if unique:
                gb_meta = unique
                stats["fallback_matched"] += 1
            elif len(candidates) > 1:
                stats["ambiguous_skipped"] += 1
                continue

        if normalized_semester:
            if normalized_semester != str(raw_semester or "").strip():
                patch["学期"] = normalized_semester
                reasons.append(f"学期规范化: {raw_semester} -> {normalized_semester}")
                stats["semester_fixed"] += 1
                semester_changed = True
        elif gb_meta and gb_meta.get("semester"):
            patch["学期"] = gb_meta["semester"]
            reasons.append(f"补写学期: 空白 -> {gb_meta['semester']}")
            stats["semester_fixed"] += 1
            semester_changed = True

        if gb_meta and gb_meta.get("semester") and normalized_semester and gb_meta["semester"] != normalized_semester:
            stats["mismatch_skipped"] += 1
            patch.pop("学期", None)
            reasons = [r for r in reasons if not r.startswith(("补写学期", "学期规范化"))]
            if semester_changed:
                stats["semester_fixed"] -= 1

        if gb_meta and nature not in ("🔥 极其重要", "🚫 忽略"):
            patch["作业性质"] = "🔥 极其重要"
            reasons.append(f"作业性质: {nature or '空白'} -> 🔥 极其重要")
            stats["hot_fixed"] += 1

        if gb_meta and gb_meta.get("due_ms") is not None and not has_due:
            patch["截止日期"] = gb_meta["due_ms"]
            reasons.append("补写截止日期")
            stats["due_backfilled"] += 1

        if not patch:
            continue

        updates.append(
            {
                "record_id": rec_id,
                "fields": patch,
                "preview_name": patch.get("作业名称", raw_name),
                "reasons": reasons,
            }
        )

    return updates, stats


def print_plan(updates, stats, limit):
    print("=" * 70)
    print(f"计划更新记录数: {len(updates)}")
    print(
        "明细统计: "
        f"学期修复={stats['semester_fixed']} "
        f"作业名修复={stats['name_fixed']} "
        f"极其重要补标={stats['hot_fixed']} "
        f"截止日期补写={stats['due_backfilled']} "
        f"兜底匹配={stats['fallback_matched']} "
        f"歧义跳过={stats['ambiguous_skipped']} "
        f"学期冲突跳过={stats['mismatch_skipped']}"
    )
    print("=" * 70)

    preview = updates[:limit]
    for item in preview:
        print(f"- {item['record_id']} | {item['preview_name']}")
        for reason in item["reasons"]:
            print(f"    {reason}")
    if len(updates) > len(preview):
        print(f"... 还有 {len(updates) - len(preview)} 条未展示")


def main():
    parser = argparse.ArgumentParser(description="一次性清洗飞书作业库历史脏数据")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写回飞书；默认仅 dry-run 预览",
    )
    parser.add_argument(
        "--preview-limit",
        type=int,
        default=30,
        help="dry-run 时最多预览多少条（默认 30）",
    )
    args = parser.parse_args()

    cfg = get_env_config()
    token = get_feishu_token(cfg)

    print(">>> 读取飞书作业库...")
    lib_records = fetch_all_records(token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_LIB_TABLE_ID"])
    print(f"    作业库记录数: {len(lib_records)}")

    print(">>> 读取飞书 Gradebook...")
    gradebook_rows = fetch_all_records(token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"])
    print(f"    Gradebook 记录数: {len(gradebook_rows)}")

    updates, stats = plan_lib_updates(lib_records, gradebook_rows)
    print_plan(updates, stats, args.preview_limit)

    if not args.apply:
        print("\n[dry-run] 未写入飞书。确认无误后执行: python cleanup_lib_data.py --apply")
        return

    payload = [{"record_id": item["record_id"], "fields": item["fields"]} for item in updates]
    if not payload:
        print("\n[apply] 无需更新。")
        return

    print(f"\n>>> 开始写回飞书，共 {len(payload)} 条...")
    batch_update_records(token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_LIB_TABLE_ID"], payload)
    print("[apply] 写回完成。")


if __name__ == "__main__":
    main()
