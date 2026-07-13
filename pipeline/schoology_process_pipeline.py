"""
schoology_process_pipeline.py

Builds the first-pass Schoology academic-process data layer.

This script intentionally runs alongside the existing Feishu pipeline. It reads:
  - Schoology Materials pages
  - Schoology Gradebook iAPI + Grade Setup
  - existing Feishu submission records, when Feishu env vars are available

It writes normalized process tables to PostgreSQL when DATABASE_URL is set, and
always writes a local JSON snapshot for debugging.
"""

import calendar
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import requests


BASE_URL = "https://queenscanada.schoology.com"

DEFAULT_COURSE_MAPPING = {
    "grade 11 physics": "SPH3U",
    "grade 12 physics": "SPH4U",
    "grade 11 chemistry": "SCH3U",
    "grade 12 chemistry": "SCH4U",
    "grade 11 computer science": "ICS3U",
    "grade 12 computer science": "ICS4U",
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
    "g12 international business fundamentals": "BBB4M",
    "grade 12 simplified chinese": "LKBDU",
    "grade 11 biology": "SBI3U",
    "grade 10 science": "SNC2D",
    "esl level 5": "ESLEO",
    "esl level 4": "ESLDO",
    "esl level 3": "ESLCO",
    "esl level 2": "ESLBO",
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_course_title(title):
    return re.sub(r"\s+", " ", str(title or "").split(":")[0].strip().lower())


def resolve_course_code(title):
    normalized = normalize_course_title(title)
    return DEFAULT_COURSE_MAPPING.get(normalized, str(title or "").split(":")[0].strip())


def parse_semester_label(title):
    """Return school-year-start label, e.g. 2526S4N -> 2025-S4."""
    m = re.search(r"(\d{2})(\d{2})(S\d)N", str(title or ""), re.IGNORECASE)
    if not m:
        return ""
    return f"20{m.group(1)}-{m.group(3).upper()}"


def parse_sem_short(title):
    m = re.search(r"\d{4}(S\d)N", str(title or ""), re.IGNORECASE)
    return m.group(1).upper() if m else ""


def hydrate_section_from_materials(section, folders):
    """Backfill section metadata from the root Materials page when only a nid was provided."""
    root = next((folder for folder in folders if folder.get("folder_id") == "root"), None)
    title = str((root or {}).get("title") or "").strip()
    if not title or title.lower() == "root":
        return section
    hydrated = dict(section)
    if not hydrated.get("title") or hydrated["title"] == hydrated.get("section_nid"):
        hydrated["title"] = title
    if not hydrated.get("course_code") or hydrated["course_code"] == hydrated.get("section_nid"):
        hydrated["course_code"] = resolve_course_code(hydrated["title"])
    if not hydrated.get("semester"):
        hydrated["semester"] = parse_semester_label(hydrated["title"])
    if not hydrated.get("sem_short"):
        hydrated["sem_short"] = parse_sem_short(hydrated["title"])
    return hydrated


def clean_schoology_url(url):
    text = str(url or "").strip()
    if not text:
        return ""
    m = re.search(
        r"(https://.*?(?:/(?:assignment|assessment|discussion)/\d+|/materials/discussion/view/\d+))",
        text,
    )
    return m.group(1) if m else text


def material_id_from_url(url):
    m = re.search(r"(?:/(?:assignment|assessment|discussion)/|/materials/discussion/view/)(\d+)", str(url or ""))
    return m.group(1) if m else ""


def material_type_from_url(url):
    text = str(url or "")
    if "/assessment/" in text or "/assessments/" in text:
        return "assessment"
    if "/discussion/" in text or "/materials/discussion/view/" in text:
        return "discussion"
    if "/assignment/" in text:
        return "assignment"
    if "/materials?f=" in text:
        return "folder"
    return "material"


def parse_schoology_due(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y at %I:%M %p", "%b %d, %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return datetime.fromtimestamp(calendar.timegm(dt.timetuple()), timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def parse_feishu_time(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    text = str(value).strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            # Existing records are authored in Asia/Shanghai local time; keep as observed text in payload.
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def load_sections():
    raw = os.environ.get("SCHOOLOGY_SECTION_NIDS", "").strip()
    if raw:
        raw = re.sub(r"[\x00-\x1f\x7f]", "", raw)
        parsed = json.loads(raw)
    else:
        single_nid = os.environ.get("SCHOOLOGY_SECTION_NID", "").strip()
        single_title = os.environ.get("SCHOOLOGY_SECTION_TITLE", "").strip()
        if not single_nid:
            raise ValueError("SCHOOLOGY_SECTION_NIDS or SCHOOLOGY_SECTION_NID is required")
        parsed = {single_nid: single_title or single_nid}
    sections = []
    for section_nid, title in parsed.items():
        section_nid = str(section_nid).strip()
        if not re.match(r"^\d+$", section_nid):
            print(f"[skip] invalid section_nid={section_nid!r}")
            continue
        sections.append(
            {
                "section_nid": section_nid,
                "title": str(title or "").strip(),
                "course_code": resolve_course_code(title),
                "semester": parse_semester_label(title),
                "sem_short": parse_sem_short(title),
            }
        )
    if not sections:
        raise ValueError("No valid Schoology sections found")
    return sections


def build_schoology_session():
    raw = os.environ.get("SCHOOLOGY_COOKIES", "").strip()
    if not raw:
        raise ValueError("SCHOOLOGY_COOKIES is required")
    cookies = json.loads(raw)
    session = requests.Session()
    for ck in cookies:
        session.cookies.set(
            ck["name"],
            ck["value"],
            domain=ck.get("domain", ".queenscanada.schoology.com"),
            path=ck.get("path", "/"),
        )
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": BASE_URL,
        }
    )
    return session


def request_text(session, path, accept="text/html,application/xhtml+xml"):
    url = path if str(path).startswith("http") else f"{BASE_URL}{path}"
    headers = {"Accept": accept}
    if "json" in accept:
        headers["X-Requested-With"] = "XMLHttpRequest"
    for attempt in range(3):
        resp = session.get(url, headers=headers, timeout=30, allow_redirects=True)
        if resp.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        break
    if "login" in resp.url.lower() or resp.status_code in (401, 403):
        raise RuntimeError(f"Schoology auth failed for {url}: status={resp.status_code} final={resp.url}")
    return resp


def verify_cookies(session):
    resp = request_text(session, "/home")
    print(f"Schoology cookie ok: HTTP {resp.status_code}")


def parse_links(page_html):
    for m in re.finditer(r'<a\b([^>]*)href="([^"]+)"([^>]*)>(.*?)</a>', page_html, re.I | re.S):
        href = html.unescape(m.group(2))
        label = clean_text(m.group(4))
        yield label, href, f"{m.group(1)} {m.group(3)}"


def crawl_materials(session, section):
    section_nid = section["section_nid"]
    queue = [f"/course/{section_nid}/materials"]
    seen_paths = set()
    folders = {}
    assignments = {}
    events = []

    while queue:
        path = queue.pop(0)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        resp = request_text(session, path)
        page_html = resp.text
        folder_id = parse_qs(urlparse(path).query).get("f", ["root"])[0]
        page_title = clean_text(re.search(r"<title>(.*?)</title>", page_html, re.I | re.S).group(1)) if re.search(r"<title>(.*?)</title>", page_html, re.I | re.S) else ""
        folders[folder_id] = {
            "folder_id": folder_id,
            "section_nid": section_nid,
            "title": page_title.replace(" | Schoology", "") or ("root" if folder_id == "root" else folder_id),
            "parent_folder_id": None,
            "url": urljoin(BASE_URL, path),
            "raw": {"page_title": page_title},
        }

        for label, href, _attrs in parse_links(page_html):
            full_url = urljoin(BASE_URL, href)
            if f"/course/{section_nid}/materials?f=" in href:
                child_id = parse_qs(urlparse(href).query).get("f", [""])[0]
                if child_id and href not in seen_paths and href not in queue:
                    queue.append(href)
                folders.setdefault(
                    child_id,
                    {
                        "folder_id": child_id,
                        "section_nid": section_nid,
                        "title": re.sub(r"^Folder\.\s*", "", label).strip() or child_id,
                        "parent_folder_id": folder_id,
                        "url": full_url,
                        "raw": {},
                    },
                )
            if re.search(r"(?:/(?:assignment|assessment|discussion)/|/materials/discussion/view/)\d+", href):
                schoology_id = material_id_from_url(href)
                if not schoology_id:
                    continue
                key = f"{section_nid}:{schoology_id}"
                title = re.sub(r"^(Edit|Copy to Course|Delete|Save to Resources)\s*$", "", label).strip()
                if not title:
                    continue
                assignments[key] = {
                    "assignment_key": key,
                    "schoology_id": schoology_id,
                    "section_nid": section_nid,
                    "title": title,
                    "type": material_type_from_url(href),
                    "url": full_url,
                    "folder_id": folder_id,
                    "source": "materials",
                    "current_stage": "discovered",
                    "requiredness": "unknown",
                    "grade_status": "not_in_gradebook",
                    "scope_type": "unknown",
                    "first_seen_at": utc_now_iso(),
                    "last_seen_at": utc_now_iso(),
                    "raw": {},
                }
                events.append(
                    {
                        "event_key": stable_key("assignment_event", key, "discovered_in_materials"),
                        "assignment_key": key,
                        "student_uid": None,
                        "event_type": "discovered_in_materials",
                        "event_time": utc_now_iso(),
                        "source": "materials",
                        "evidence_url": full_url,
                        "payload": {"folder_id": folder_id},
                    }
                )

    return list(folders.values()), list(assignments.values()), events


def fetch_gradesetup_weights(session, section_nid):
    resp = request_text(session, f"/course/{section_nid}/gradesetup")
    weights = {}
    for row_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", resp.text, re.S | re.I):
        row_html = row_m.group(1)
        wt_m = re.search(r'weight_percentage[^>]*>.*?<span[^>]*title="([\d.]+)%"', row_html, re.S)
        cid_m = re.search(r"edit-categories-(\d+)-weight", row_html)
        if not wt_m or not cid_m:
            continue
        cat_id = cid_m.group(1)
        name_m = re.search(rf'href="[^"]*/{cat_id}[^"]*"[^>]*>\s*([^<]+?)\s*</a>', row_html, re.S)
        if not name_m:
            continue
        title = clean_text(name_m.group(1))
        if title:
            weights[title.strip().lower()] = {"category_id": cat_id, "title": title, "weight_pct": float(wt_m.group(1))}
    return weights


def crawl_gradebook(session, section):
    section_nid = section["section_nid"]
    weights = fetch_gradesetup_weights(session, section_nid)
    resp = request_text(session, f"/iapi/grades/grader_header_data/{section_nid}", accept="application/json")
    data = resp.json().get("body", resp.json())

    categories = []
    cat_titles = {}
    for cat in data.get("grading_categories") or []:
        cat_id = str(cat.get("id", ""))
        title = str(cat.get("title", "")).strip()
        cat_titles[cat_id] = title
        if cat_id in ("all", "summary"):
            continue
        wt = weights.get(title.strip().lower(), {})
        categories.append(
            {
                "category_key": f"{section_nid}:{cat_id}",
                "category_id": cat_id,
                "section_nid": section_nid,
                "title": title,
                "weight_pct": wt.get("weight_pct"),
                "raw": cat,
            }
        )

    enrollments = []
    grade_items = []
    grade_records = []
    assignments = []
    events = []
    user_data = data.get("user_data") or {}
    grades = data.get("grades") or {}
    item_data = data.get("grade_item_data") or {}

    for uid, student in user_data.items():
        name = str(student.get("name", "")).strip()
        if not name:
            continue
        enrollments.append(
            {
                "enrollment_key": f"{section_nid}:{uid}",
                "section_nid": section_nid,
                "student_uid": str(uid),
                "student_name": name,
                "course_code": section["course_code"],
                "semester": section["semester"],
                "role": "student",
                "source": "gradebook",
                "raw": student,
            }
        )

    for item_nid, item in item_data.items():
        if item.get("is_grade_column") or item.get("exclude_from_grade"):
            continue
        category_id = str(item.get("grading_category_id", ""))
        category_title = cat_titles.get(category_id, item.get("category_title", ""))
        category_weight = weights.get(str(category_title).strip().lower(), {}).get("weight_pct")
        assignment_key = f"{section_nid}:{item_nid}"
        due_at = parse_schoology_due(item.get("due_date_text"))
        grade_items.append(
            {
                "grade_item_key": assignment_key,
                "grade_item_nid": str(item_nid),
                "assignment_key": assignment_key,
                "section_nid": section_nid,
                "title": str(item.get("title", "")).strip(),
                "category_id": category_id,
                "category_title": category_title,
                "category_weight_pct": category_weight,
                "max_points": item.get("max_points"),
                "due_at": due_at,
                "raw": item,
            }
        )
        assignments.append(
            {
                "assignment_key": assignment_key,
                "schoology_id": str(item_nid),
                "section_nid": section_nid,
                "title": str(item.get("title", "")).strip(),
                "type": "grade_item",
                "url": f"{BASE_URL}/assignment/{item_nid}",
                "folder_id": None,
                "source": "gradebook",
                "current_stage": "entered_gradebook",
                "requiredness": "required",
                "grade_status": "in_gradebook",
                "scope_type": "whole_class",
                "first_seen_at": utc_now_iso(),
                "last_seen_at": utc_now_iso(),
                "raw": {"category_title": category_title, "due_at": due_at},
            }
        )
        events.append(
            {
                "event_key": stable_key("assignment_event", assignment_key, "entered_gradebook"),
                "assignment_key": assignment_key,
                "student_uid": None,
                "event_type": "entered_gradebook",
                "event_time": utc_now_iso(),
                "source": "gradebook",
                "evidence_url": f"{BASE_URL}/course/{section_nid}/grades",
                "payload": {"category_title": category_title, "max_points": item.get("max_points"), "due_at": due_at},
            }
        )

        for uid, student in user_data.items():
            entry = (grades.get(str(uid)) or {}).get(str(item_nid)) or {}
            overall_raw = (student.get("grades") or {}).get("overall") or (student.get("grades") or {}).get("all") or {}
            score = entry.get("grade")
            max_points = item.get("max_points") or 0
            pct = round(score / max_points * 100, 2) if score is not None and max_points else None
            grade_records.append(
                {
                    "grade_record_key": f"{section_nid}:{uid}:{item_nid}",
                    "grade_item_key": assignment_key,
                    "assignment_key": assignment_key,
                    "section_nid": section_nid,
                    "student_uid": str(uid),
                    "student_name": str(student.get("name", "")).strip(),
                    "score": score,
                    "max_points": max_points,
                    "pct": pct,
                    "overall_course_grade": overall_raw.get("numeric") if isinstance(overall_raw, dict) else None,
                    "submission_status": entry.get("submission", ""),
                    "exception": entry.get("exception"),
                    "comment_text": (entry.get("comment") or {}).get("text") if isinstance(entry.get("comment"), dict) else "",
                    "observed_at": utc_now_iso(),
                    "raw": entry,
                }
            )
    return categories, enrollments, assignments, events, grade_items, grade_records


def feishu_token(app_id, app_secret):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    ).json()
    token = resp.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"Feishu token failed: {resp}")
    return token


def fetch_feishu_records(token, app_token, table_id):
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
            raise RuntimeError(f"Feishu record fetch failed table={table_id}: {resp}")
        data = resp.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


def extract_link(value):
    if isinstance(value, dict):
        return value.get("link") or value.get("text") or ""
    return str(value or "")


def strip_tags(value):
    return clean_text(value)


def parse_schoology_notification_time(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^Posted on\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[A-Za-z]+,\s+", "", text)
    for fmt in ("%b %d, %Y at %I:%M %p", "%b %d at %I:%M %p"):
        try:
            dt = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=datetime.now(timezone.utc).year)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return parse_feishu_time(text)


def infer_submission_type(url="", raw_text="", title=""):
    text = " ".join(str(part or "") for part in (url, raw_text, title)).lower()
    if "/discussion/" in text or " discussion " in f" {text} " or "discussion board" in text:
        return "discussion_post"
    if "/assessment/" in text or " assessment " in f" {text} ":
        return "assessment_submission"
    if "test/quiz" in text:
        return "quiz_submission"
    return "assignment_submission"


def split_notification_students(student_text):
    text = re.sub(r"\s+", " ", str(student_text or "")).strip()
    if not text:
        return []
    text = re.sub(r"\band\s+\d+\s+other\s+(?:person|people)\b", "", text, flags=re.IGNORECASE).strip()
    text = text.replace(" ,", ",")
    parts = re.split(r"\s*,\s*|\s+and\s+", text)
    students = []
    seen = set()
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" ,")
        if not name or re.search(r"\bother\s+(?:person|people)\b", name, re.IGNORECASE):
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            students.append(name)
    return students


def extract_discussion_response_events_from_html(page_html):
    events = []
    blocks = re.split(r"(?=<li><div class='s-edge-type-)", page_html)
    for item_html in blocks:
        if "s-edge-type-comment-add" not in item_html or "replied to" not in item_html:
            continue
        discussion_match = re.search(
            r'<a href="([^"]*/materials/discussion/view/(\d+)[^"]*)">(.*?)</a>\s*<span class="edge-time">(.*?)</span>',
            item_html,
            re.I | re.S,
        )
        if not discussion_match:
            continue
        discussion_url = urljoin(BASE_URL, html.unescape(discussion_match.group(1)))
        discussion_id = discussion_match.group(2)
        discussion_title = strip_tags(discussion_match.group(3))
        submitted_at = parse_schoology_notification_time(strip_tags(discussion_match.group(4)))
        section_match = re.search(r"/course/(\d+)/materials/discussion/view/", discussion_url)
        section_nid = section_match.group(1) if section_match else ""

        student_links = re.findall(
            r'class=[\'"]user-item[\'"].*?<a href="/user/(\d+)"[^>]*>(.*?)</a>\s*<span class=[\'"]comment-created[\'"]>(.*?)</span>',
            item_html,
            re.I | re.S,
        )
        if not student_links:
            sentence_match = re.search(r"<span class='edge-sentence'>(.*?)replied to", item_html, re.I | re.S)
            if sentence_match:
                student_links = [
                    (uid, label, strip_tags(discussion_match.group(4)))
                    for uid, label in re.findall(r'<a href="/user/(\d+)"[^>]*>(.*?)</a>', sentence_match.group(1), re.I | re.S)
                ]

        for student_uid, student_label, posted_text in student_links:
            student_name = strip_tags(student_label)
            if not student_name:
                continue
            event_time = parse_schoology_notification_time(strip_tags(posted_text)) or submitted_at
            raw_text = f"{student_name} replied to {discussion_title} {strip_tags(discussion_match.group(4))}"
            events.append(
                {
                    "submission_event_key": stable_key("discussion_response", section_nid, discussion_id, student_uid, event_time),
                    "assignment_key": f"{section_nid}:{discussion_id}" if section_nid else f"unknown:{discussion_id}",
                    "schoology_id": discussion_id,
                    "student_uid": str(student_uid),
                    "student_name": student_name,
                    "assignment_title": discussion_title,
                    "assignment_url": discussion_url,
                    "section_nid": section_nid,
                    "status": "replied",
                    "submission_type": "discussion_post",
                    "submitted_at": event_time,
                    "source": "schoology_notification",
                    "raw_text": raw_text,
                    "payload": {"notification_type": "discussion_response", "posted_text": strip_tags(posted_text)},
                }
            )
    return events


def fetch_schoology_notification_events(session):
    if os.environ.get("SCHOOLOGY_FETCH_NOTIFICATIONS", "1").strip() == "0":
        return []
    resp = request_text(session, "/home/notifications?from_popup&")
    return extract_discussion_response_events_from_html(resp.text)


def build_submission_events_from_feishu():
    required = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", "FEISHU_TABLE_ID"]
    if any(not os.environ.get(k, "").strip() for k in required):
        print("Feishu submission env not complete; skipping submission_events import")
        return []
    token = feishu_token(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"])
    records = fetch_feishu_records(token, os.environ["FEISHU_APP_TOKEN"], os.environ["FEISHU_TABLE_ID"])
    events = []
    for rec in records:
        f = rec.get("fields", {})
        url = clean_schoology_url(extract_link(f.get("作业链接")))
        assignment_id = material_id_from_url(url)
        if not url or not assignment_id:
            continue
        student_name = str(f.get("学生姓名", "")).strip()
        status = str(f.get("提交状态", "") or "submitted").strip().lower()
        raw_text = str(f.get("原始通知", "")).strip()
        submitted_at = parse_feishu_time(f.get("提交时间"))
        assignment_title = str(f.get("作业名称", "")).strip()
        submission_type = infer_submission_type(url=url, raw_text=raw_text, title=assignment_title)
        student_names = split_notification_students(student_name) or [student_name]
        # Section is filled later by assignment/course enrichment where possible.
        assignment_key = f"unknown:{assignment_id}"
        base_dedupe = str(f.get("唯一ID", "")).strip()
        for parsed_student_name in student_names:
            dedupe = stable_key("submission", base_dedupe, parsed_student_name) if base_dedupe else stable_key(
                "submission",
                parsed_student_name,
                assignment_id,
                submitted_at,
                raw_text,
            )
            events.append(
                {
                    "submission_event_key": dedupe,
                    "assignment_key": assignment_key,
                    "schoology_id": assignment_id,
                    "student_uid": "",
                    "student_name": parsed_student_name,
                    "assignment_title": assignment_title,
                    "assignment_url": url,
                    "section_nid": "",
                    "status": "resubmitted" if "resub" in status else "submitted",
                    "submission_type": submission_type,
                    "submitted_at": submitted_at,
                    "source": "feishu_submission_table",
                    "raw_text": raw_text,
                    "payload": {
                        "feishu_record_id": rec.get("record_id"),
                        "fields": f,
                        "original_student_name": student_name,
                        "submission_type": submission_type,
                    },
                }
            )
    return events


def stable_key(*parts):
    text = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def merge_assignments(assignments):
    merged = {}
    stage_rank = {"discovered": 1, "submitted_seen": 2, "entered_gradebook": 3, "graded": 4, "resolved": 5}
    for item in assignments:
        key = item["assignment_key"]
        old = merged.get(key)
        if not old:
            merged[key] = item
            continue
        if stage_rank.get(item.get("current_stage"), 0) >= stage_rank.get(old.get("current_stage"), 0):
            merged[key] = {**old, **item, "first_seen_at": old.get("first_seen_at") or item.get("first_seen_at")}
    return list(merged.values())


def dedupe_submission_events(events):
    deduped = {}
    for event in events:
        key = event.get("submission_event_key") or stable_key(
            "submission",
            event.get("student_name"),
            event.get("schoology_id"),
            event.get("submitted_at"),
            event.get("raw_text"),
        )
        if key not in deduped:
            deduped[key] = event
    return list(deduped.values())


def enrich_submission_assignments(submission_events, assignments, keep_unknown=False):
    by_id = {}
    for a in assignments:
        if a.get("schoology_id"):
            by_id.setdefault(str(a["schoology_id"]), a)
    new_assignments = []
    assignment_events = []
    scoped_events = []
    for ev in submission_events:
        known = by_id.get(str(ev.get("schoology_id", "")))
        if known:
            ev["assignment_key"] = known["assignment_key"]
            ev["section_nid"] = known.get("section_nid", "")
            scoped_events.append(ev)
        else:
            if not keep_unknown:
                continue
            scoped_events.append(ev)
            new_assignments.append(
                {
                    "assignment_key": ev["assignment_key"],
                    "schoology_id": ev["schoology_id"],
                    "section_nid": "",
                    "title": ev.get("assignment_title") or ev.get("schoology_id"),
                    "type": material_type_from_url(ev.get("assignment_url")),
                    "url": ev.get("assignment_url"),
                    "folder_id": None,
                    "source": "notification",
                    "current_stage": "submitted_seen",
                    "requiredness": "unknown",
                    "grade_status": "not_in_gradebook",
                    "scope_type": "unknown",
                    "first_seen_at": ev.get("submitted_at") or utc_now_iso(),
                    "last_seen_at": utc_now_iso(),
                    "raw": {},
                }
            )
        assignment_events.append(
            {
                "event_key": stable_key("assignment_event", ev["assignment_key"], ev["student_name"], ev["submitted_at"], ev["status"]),
                "assignment_key": ev["assignment_key"],
                "student_uid": ev.get("student_uid") or None,
                "event_type": "resubmitted_seen" if ev["status"] == "resubmitted" else "submitted_seen",
                "event_time": ev.get("submitted_at") or utc_now_iso(),
                "source": "notification",
                "evidence_url": ev.get("assignment_url"),
                "payload": {"student_name": ev.get("student_name"), "raw_text": ev.get("raw_text")},
            }
        )
    return scoped_events, new_assignments, assignment_events


def build_risks(assignments, submission_events, grade_records):
    submissions_by_student_assignment = {(ev.get("student_name", ""), ev.get("assignment_key", "")) for ev in submission_events}
    submitted_counts = {}
    for ev in submission_events:
        submitted_counts[ev.get("assignment_key", "")] = submitted_counts.get(ev.get("assignment_key", ""), 0) + 1
    assignment_lookup = {a["assignment_key"]: a for a in assignments}
    risks = []

    for gr in grade_records:
        assignment_key = gr["assignment_key"]
        assignment = assignment_lookup.get(assignment_key, {})
        due_at = (assignment.get("raw") or {}).get("due_at")
        has_submission = (gr.get("student_name", ""), assignment_key) in submissions_by_student_assignment
        if gr.get("score") is None and not has_submission:
            risks.append(
                {
                    "risk_key": stable_key("risk", "hard_missing", gr["student_uid"], assignment_key),
                    "student_uid": gr["student_uid"],
                    "student_name": gr["student_name"],
                    "assignment_key": assignment_key,
                    "section_nid": gr["section_nid"],
                    "risk_type": "hard_missing",
                    "risk_level": "red",
                    "status": "open",
                    "evidence_source": "gradebook",
                    "evidence": {
                        "score": gr.get("score"),
                        "max_points": gr.get("max_points"),
                        "submission_status": gr.get("submission_status"),
                        "due_at": due_at,
                    },
                    "created_at": utc_now_iso(),
                }
            )
        if gr.get("pct") is not None and gr["pct"] < float(os.environ.get("SCHOOLOGY_LOW_SCORE_THRESHOLD", "60")):
            risks.append(
                {
                    "risk_key": stable_key("risk", "low_score", gr["student_uid"], assignment_key, gr.get("pct")),
                    "student_uid": gr["student_uid"],
                    "student_name": gr["student_name"],
                    "assignment_key": assignment_key,
                    "section_nid": gr["section_nid"],
                    "risk_type": "low_score",
                    "risk_level": "yellow",
                    "status": "open",
                    "evidence_source": "gradebook",
                    "evidence": {"pct": gr.get("pct"), "score": gr.get("score"), "max_points": gr.get("max_points")},
                    "created_at": utc_now_iso(),
                }
            )

    # Soft risks: if a notification-only task has classmates submitting it, keep as suspected for review.
    for assignment_key, count in submitted_counts.items():
        if count < int(os.environ.get("SCHOOLOGY_SUSPECTED_MISSING_MIN_SUBMISSIONS", "3")):
            continue
        assignment = assignment_lookup.get(assignment_key, {})
        if assignment.get("grade_status") == "in_gradebook":
            continue
        risks.append(
            {
                "risk_key": stable_key("risk", "suspected_missing_group", assignment_key),
                "student_uid": "",
                "student_name": "",
                "assignment_key": assignment_key,
                "section_nid": assignment.get("section_nid", ""),
                "risk_type": "suspected_missing",
                "risk_level": "yellow",
                "status": "needs_teacher_confirm",
                "evidence_source": "notification",
                "evidence": {"submitted_count": count, "reason": "classmates submitted but scope is unknown"},
                "created_at": utc_now_iso(),
            }
        )
    return risks


def write_snapshot(output):
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "schoology_process")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Snapshot written: {path}")


def write_postgres(output):
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL not set; skipping PostgreSQL write")
        return
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 not installed; skipping PostgreSQL write")
        return

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    create_schema(cur)
    tenant = output["tenant"]

    upsert_many(cur, "course_sections", ["tenant", "section_nid"], output["course_sections"], tenant)
    upsert_many(cur, "section_enrollments", ["tenant", "enrollment_key"], output["section_enrollments"], tenant)
    upsert_many(cur, "material_folders", ["tenant", "folder_key"], output["material_folders"], tenant)
    upsert_many(cur, "assignments", ["tenant", "assignment_key"], output["assignments"], tenant)
    upsert_many(cur, "assignment_events", ["tenant", "event_key"], output["assignment_events"], tenant)
    upsert_many(cur, "submission_events", ["tenant", "submission_event_key"], output["submission_events"], tenant)
    upsert_many(cur, "grade_items", ["tenant", "grade_item_key"], output["grade_items"], tenant)
    upsert_many(cur, "grade_records", ["tenant", "grade_record_key"], output["grade_records"], tenant)
    upsert_many(cur, "grading_categories", ["tenant", "category_key"], output["grading_categories"], tenant)
    upsert_many(cur, "risk_signals", ["tenant", "risk_key"], output["risk_signals"], tenant)

    cur.execute(
        """
        INSERT INTO sync_runs(tenant, sync_run_id, status, metrics, started_at, completed_at)
        VALUES (%s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT(tenant, sync_run_id)
        DO UPDATE SET status=EXCLUDED.status, metrics=EXCLUDED.metrics, completed_at=NOW()
        """,
        (tenant, output["sync_run_id"], "success", psycopg2.extras.Json(output["metrics"])),
    )
    conn.commit()
    cur.close()
    conn.close()
    print("PostgreSQL write complete")


def create_schema(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
          tenant TEXT NOT NULL,
          sync_run_id TEXT NOT NULL,
          status TEXT NOT NULL,
          metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
          started_at TIMESTAMPTZ DEFAULT NOW(),
          completed_at TIMESTAMPTZ,
          PRIMARY KEY (tenant, sync_run_id)
        );
        CREATE TABLE IF NOT EXISTS course_sections (
          tenant TEXT NOT NULL,
          section_nid TEXT NOT NULL,
          title TEXT,
          course_code TEXT,
          semester TEXT,
          sem_short TEXT,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, section_nid)
        );
        CREATE TABLE IF NOT EXISTS section_enrollments (
          tenant TEXT NOT NULL,
          enrollment_key TEXT NOT NULL,
          section_nid TEXT,
          student_uid TEXT,
          student_name TEXT,
          course_code TEXT,
          semester TEXT,
          role TEXT,
          source TEXT,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, enrollment_key)
        );
        CREATE TABLE IF NOT EXISTS material_folders (
          tenant TEXT NOT NULL,
          folder_key TEXT NOT NULL,
          folder_id TEXT,
          section_nid TEXT,
          title TEXT,
          parent_folder_id TEXT,
          url TEXT,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, folder_key)
        );
        CREATE TABLE IF NOT EXISTS assignments (
          tenant TEXT NOT NULL,
          assignment_key TEXT NOT NULL,
          schoology_id TEXT,
          section_nid TEXT,
          title TEXT,
          type TEXT,
          url TEXT,
          folder_id TEXT,
          source TEXT,
          current_stage TEXT,
          requiredness TEXT,
          grade_status TEXT,
          scope_type TEXT,
          first_seen_at TIMESTAMPTZ,
          last_seen_at TIMESTAMPTZ,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, assignment_key)
        );
        CREATE TABLE IF NOT EXISTS assignment_events (
          tenant TEXT NOT NULL,
          event_key TEXT NOT NULL,
          assignment_key TEXT,
          student_uid TEXT,
          event_type TEXT,
          event_time TIMESTAMPTZ,
          source TEXT,
          evidence_url TEXT,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, event_key)
        );
        CREATE TABLE IF NOT EXISTS submission_events (
          tenant TEXT NOT NULL,
          submission_event_key TEXT NOT NULL,
          assignment_key TEXT,
          schoology_id TEXT,
          student_uid TEXT,
          student_name TEXT,
          assignment_title TEXT,
          assignment_url TEXT,
          section_nid TEXT,
          status TEXT,
          submission_type TEXT,
          submitted_at TIMESTAMPTZ,
          source TEXT,
          raw_text TEXT,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, submission_event_key)
        );
        CREATE TABLE IF NOT EXISTS grade_items (
          tenant TEXT NOT NULL,
          grade_item_key TEXT NOT NULL,
          grade_item_nid TEXT,
          assignment_key TEXT,
          section_nid TEXT,
          title TEXT,
          category_id TEXT,
          category_title TEXT,
          category_weight_pct DOUBLE PRECISION,
          max_points DOUBLE PRECISION,
          due_at TIMESTAMPTZ,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, grade_item_key)
        );
        CREATE TABLE IF NOT EXISTS grade_records (
          tenant TEXT NOT NULL,
          grade_record_key TEXT NOT NULL,
          grade_item_key TEXT,
          assignment_key TEXT,
          section_nid TEXT,
          student_uid TEXT,
          student_name TEXT,
          score DOUBLE PRECISION,
          max_points DOUBLE PRECISION,
          pct DOUBLE PRECISION,
          overall_course_grade DOUBLE PRECISION,
          submission_status TEXT,
          exception TEXT,
          comment_text TEXT,
          observed_at TIMESTAMPTZ,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, grade_record_key)
        );
        CREATE TABLE IF NOT EXISTS grading_categories (
          tenant TEXT NOT NULL,
          category_key TEXT NOT NULL,
          category_id TEXT,
          section_nid TEXT,
          title TEXT,
          weight_pct DOUBLE PRECISION,
          raw JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, category_key)
        );
        CREATE TABLE IF NOT EXISTS risk_signals (
          tenant TEXT NOT NULL,
          risk_key TEXT NOT NULL,
          student_uid TEXT,
          student_name TEXT,
          assignment_key TEXT,
          section_nid TEXT,
          risk_type TEXT,
          risk_level TEXT,
          status TEXT,
          evidence_source TEXT,
          evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ,
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (tenant, risk_key)
        );
        CREATE INDEX IF NOT EXISTS idx_assignments_section ON assignments(tenant, section_nid);
        CREATE INDEX IF NOT EXISTS idx_submission_student ON submission_events(tenant, student_name);
        CREATE INDEX IF NOT EXISTS idx_grade_records_student ON grade_records(tenant, student_uid);
        CREATE INDEX IF NOT EXISTS idx_risk_signals_student ON risk_signals(tenant, student_uid, status);
        """
    )


def upsert_many(cur, table, conflict_cols, rows, tenant):
    if not rows:
        return
    import psycopg2.extras

    normalized = []
    for row in rows:
        item = dict(row)
        item["tenant"] = tenant
        if table == "material_folders":
            item["folder_key"] = f"{item.get('section_nid')}:{item.get('folder_id')}"
        normalized.append(item)
    columns = sorted({key for row in normalized for key in row.keys()})
    json_columns = {"raw", "payload", "evidence"}
    values = []
    for row in normalized:
        record = []
        for col in columns:
            value = row.get(col)
            if col in json_columns:
                value = psycopg2.extras.Json(value or {})
            record.append(value)
        values.append(record)
    assignments = ", ".join(
        f"{col}=EXCLUDED.{col}" for col in columns if col not in conflict_cols and col != "tenant"
    )
    if "updated_at" in columns:
        assignments = f"{assignments}, updated_at=NOW()" if assignments else "updated_at=NOW()"
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT({', '.join(conflict_cols)}) DO UPDATE SET {assignments}"
    )
    psycopg2.extras.execute_values(cur, sql, values)
    print(f"  {table}: upsert {len(rows)}")


def main():
    tenant = os.environ.get("CACHE_TENANT_KEY", "default").strip() or "default"
    sync_run_id = f"schoology-{int(time.time())}"
    sections = load_sections()
    schoology = build_schoology_session()
    verify_cookies(schoology)

    all_folders = []
    all_assignments = []
    all_assignment_events = []
    all_categories = []
    all_enrollments = []
    all_grade_items = []
    all_grade_records = []

    for section in sections:
        print(f"\n=== {section['course_code']} {section['section_nid']} ===")
        folders, material_assignments, material_events = crawl_materials(schoology, section)
        section.update(hydrate_section_from_materials(section, folders))
        categories, enrollments, grade_assignments, grade_events, grade_items, grade_records = crawl_gradebook(
            schoology, section
        )
        all_folders.extend(folders)
        all_assignments.extend(material_assignments)
        all_assignments.extend(grade_assignments)
        all_assignment_events.extend(material_events)
        all_assignment_events.extend(grade_events)
        all_categories.extend(categories)
        all_enrollments.extend(enrollments)
        all_grade_items.extend(grade_items)
        all_grade_records.extend(grade_records)
        print(
            f"folders={len(folders)} assignments={len(material_assignments)} "
            f"grade_items={len(grade_items)} enrollments={len(enrollments)}"
        )

    submission_events = build_submission_events_from_feishu()
    notification_events = fetch_schoology_notification_events(schoology)
    if notification_events:
        print(f"notification_events={len(notification_events)}")
        submission_events.extend(notification_events)
    submission_events = dedupe_submission_events(submission_events)
    include_unknown = os.environ.get("SCHOOLOGY_INCLUDE_UNKNOWN_SUBMISSIONS", "").strip() == "1"
    submission_events, extra_assignments, submission_assignment_events = enrich_submission_assignments(
        submission_events, all_assignments, keep_unknown=include_unknown
    )
    all_assignments.extend(extra_assignments)
    all_assignment_events.extend(submission_assignment_events)
    all_assignments = merge_assignments(all_assignments)
    risks = build_risks(all_assignments, submission_events, all_grade_records)

    output = {
        "tenant": tenant,
        "sync_run_id": sync_run_id,
        "course_sections": sections,
        "section_enrollments": all_enrollments,
        "material_folders": all_folders,
        "assignments": all_assignments,
        "assignment_events": all_assignment_events,
        "submission_events": submission_events,
        "grade_items": all_grade_items,
        "grade_records": all_grade_records,
        "grading_categories": all_categories,
        "risk_signals": risks,
        "metrics": {
            "sections": len(sections),
            "folders": len(all_folders),
            "assignments": len(all_assignments),
            "assignment_events": len(all_assignment_events),
            "submission_events": len(submission_events),
            "grade_items": len(all_grade_items),
            "grade_records": len(all_grade_records),
            "grading_categories": len(all_categories),
            "section_enrollments": len(all_enrollments),
            "risk_signals": len(risks),
        },
    }
    write_snapshot(output)
    write_postgres(output)
    print(json.dumps(output["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
