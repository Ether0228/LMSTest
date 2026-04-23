"""
scrape_gradebook.py
从 Schoology /iapi/grades/grader_header_data/{section_nid} 爬取成绩册，
写入飞书 Gradebook 表（每行 = 一个学生 × 一道作业）。

必需环境变量:
  FEISHU_APP_ID
  FEISHU_APP_SECRET
  FEISHU_APP_TOKEN
  FEISHU_GRADEBOOK_TABLE_ID   飞书 Gradebook 表 ID（新建一张表）
  SCHOOLOGY_COOKIES            与现有爬虫相同的 JSON cookie 数组
  SCHOOLOGY_SECTION_NIDS       JSON 对象，格式 {"section_nid": "课程名", ...}
                               例：{"8173239667": "Grade 11 Functions"}
"""

import os
import json
import re
import time
import calendar
import requests
from datetime import datetime


BASE_URL = "https://queenscanada.schoology.com"

# 课程全名 → 课程代码的默认映射（代码 fallback，优先从飞书系统配置表读取）
DEFAULT_COURSE_MAPPING = {
    "grade 11 physics":                    "SPH3U",
    "grade 12 physics":                    "SPH4U",
    "grade 11 chemistry":                  "SCH3U",
    "grade 12 chemistry":                  "SCH4U",
    "grade 11 computer science":           "ICS3U",
    "grade 12 data management":            "MDM4U",
    "grade 12 advanced functions":         "MHF4U",
    "grade 11 functions":                  "MCR3U",
    "grade 12 calculus & vectors":         "MCV4U",
    "grade 12 english":                    "ENG4U",
    "grade 11 english":                    "ENG3U",
    "grade 11 food and culture":           "HFC3M",
    "grade 12 nutrition & health":         "HFA4U",
    "grade 11 visual arts":                "AVI3M",
    "grade 12 visual arts":                "AVI4M",
    "grade 12 fashion":                    "HNB4M",
    "g10 canadian history since wwi":      "CHC2D",
    "grade 12 canadian and world issues":  "CGW4U",
    "grade 12 business leadership":        "BOH4M",
    "g12 analysing current economic issues": "CIA4U",
    "esl level 5":                         "ESLEO",
    "esl level 4":                         "ESLDO",
    "esl level 3":                         "ESLCO",
    "esl level 2":                         "ESLBO",
}


# ──────────────────────────────────────────────
# 配置读取
# ──────────────────────────────────────────────

def get_env_config():
    required_keys = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN", "FEISHU_GRADEBOOK_TABLE_ID",
        "SCHOOLOGY_COOKIES", "SCHOOLOGY_SECTION_NIDS",
    ]
    # FEISHU_LIB_TABLE_ID 可选：有则在 scrape 后同步更新作业库
    # FEISHU_CONFIG_TABLE_ID 可选：有则把学期区间写入飞书系统配置表
    # FEISHU_ROSTER_TABLE_ID 可选：有则在 scrape 后把选课写入花名册"所属课程"字段
    optional_keys = ["FEISHU_LIB_TABLE_ID", "FEISHU_CONFIG_TABLE_ID", "FEISHU_ROSTER_TABLE_ID"]
    cfg = {k: os.environ.get(k, "").strip() for k in required_keys + optional_keys}
    missing = [k for k in required_keys if not cfg[k]]
    if missing:
        raise ValueError(f"缺少环境变量: {', '.join(missing)}")
    return cfg


# ──────────────────────────────────────────────
# Schoology：用 cookies 建 requests.Session
# ──────────────────────────────────────────────

def notify_feishu_alert(msg: str):
    """向飞书群机器人发送告警，FEISHU_WEBHOOK_URL 未设置时静默跳过。"""
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    try:
        requests.post(webhook, json={
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "🔑 Schoology Cookie 已过期"},
                    "template": "orange"
                },
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": msg}}]
            }
        }, timeout=10)
    except Exception:
        pass  # 通知失败不影响主流程


def verify_cookies(session: requests.Session):
    """用轻量请求验证 Cookie 是否有效，过期则发飞书告警并抛出异常。"""
    resp = session.get(f"{BASE_URL}/home", timeout=15, allow_redirects=True)
    expired = (
        "login" in resp.url.lower() or
        resp.status_code in (401, 403)
    )
    if expired:
        msg = (
            "**Schoology Cookie 已过期**，爬虫无法登录。\n\n"
            "请重新获取 Cookie 并更新 GitHub Secret `SCHOOLOGY_COOKIES`。\n\n"
            f"当前 URL: `{resp.url}`"
        )
        print(f"❌ Cookie 验证失败: {resp.url}")
        notify_feishu_alert(msg)
        raise RuntimeError("COOKIE_EXPIRED: Schoology Cookie 已过期，请更新 SCHOOLOGY_COOKIES")
    print(f"✅ Cookie 验证通过 (HTTP {resp.status_code})")


def build_session(cookies_json: list) -> requests.Session:
    """把 Selenium 格式的 cookie 数组转成 requests.Session。"""
    session = requests.Session()
    for ck in cookies_json:
        session.cookies.set(
            ck["name"], ck["value"],
            domain=ck.get("domain", ".queenscanada.schoology.com"),
            path=ck.get("path", "/"),
        )
    # 模拟浏览器 UA，避免被拒绝
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE_URL,
    })
    return session


def fetch_gradebook(session: requests.Session, section_nid: str) -> dict:
    url = f"{BASE_URL}/iapi/grades/grader_header_data/{section_nid}"
    print(f"  → GET {url}")
    for attempt in range(3):
        resp = session.get(url, timeout=30, allow_redirects=True)
        print(f"  ← HTTP {resp.status_code}  final_url={resp.url}")
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            print(f"  [429] 请求限速，等待 {wait}s 后重试 ({attempt+1}/3)...")
            time.sleep(wait)
            continue
        break
    if not resp.text.strip():
        raise ValueError("响应为空（cookies 可能已过期，请更新 SCHOOLOGY_COOKIES）")
    if resp.text.strip().startswith("<"):
        raise ValueError(f"返回 HTML 而非 JSON（被重定向到登录页）: {resp.text[:200]}")
    return resp.json()


def fetch_gradesetup_weights(session: requests.Session, section_nid: str) -> dict:
    """抓取 gradesetup 页面，返回 {category_title: weight_pct} 映射。"""
    url = f"{BASE_URL}/course/{section_nid}/gradesetup"
    try:
        for attempt in range(3):
            resp = session.get(url, timeout=30)
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  [gradesetup] 429 限速，等待 {wait}s 后重试 ({attempt+1}/3)...")
                time.sleep(wait)
                continue
            break
        if resp.status_code != 200 or resp.text.strip().startswith("{"):
            print(f"  [gradesetup] HTTP {resp.status_code}，跳过")
            return {}
        html = resp.text
    except Exception as e:
        print(f"  [警告] gradesetup 获取失败: {e}")
        return {}

    has_wp = "weight_percentage" in html
    has_cat = "data-category-id" in html
    print(f"  [gradesetup] has_weight_percentage={has_wp}, has_category_id={has_cat}, html_len={len(html)}")

    weights = {}   # title → weight_pct

    # HTML 结构（已确认）：
    #   <input id="edit-categories-{id}-weight" value="{weight}">
    #   <td class="weight_percentage"><span title="10.00000%">10.00</span>%</td>
    #   <span data-category-id="{id}" href="/grading_category/.../course/{nid}/{id}" ...>（无文字）
    # 分类名在同行更早位置的 <a> 链接文本中，href 含同一 category id
    for row_m in re.finditer(r'<tr\b[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE):
        row_html = row_m.group(1)

        # 提取权重
        wt_m = re.search(r'weight_percentage[^>]*>.*?<span[^>]*title="([\d.]+)%"', row_html, re.DOTALL)
        if not wt_m:
            continue

        # 从 input id 提取 category id
        cid_m = re.search(r'edit-categories-(\d+)-weight', row_html)
        if not cid_m:
            continue
        cat_id = cid_m.group(1)

        # 从同行 href 含该 category id 的 <a> 提取分类名
        name_m = re.search(
            rf'href="[^"]*/{cat_id}[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
            row_html, re.DOTALL
        )
        if not name_m:
            continue
        title = re.sub(r'\s+', ' ', name_m.group(1)).strip()
        if title:
            try:
                weights[title] = round(float(wt_m.group(1)), 4)
            except ValueError:
                pass

    if weights:
        print(f"  [gradesetup] 读取到 {len(weights)} 个分类权重: {weights}")
    else:
        print(f"  [gradesetup] 未能提取权重（尝试 fallback）")

    return weights


# ──────────────────────────────────────────────
# 解析：把 API 响应拍平成行列表
# ──────────────────────────────────────────────

def strip_html(text: str) -> str:
    """去掉 HTML 标签，提取纯文本数字（用于 display 字段）。"""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def parse_grading_period_dates(data: dict) -> dict:
    """
    从 API 响应的 grading_period.title 提取学期起止日期。
    格式示例: "Session 3: 1/05/26 - 2/28/26"
    返回: {"start_date": "2026-01-05", "end_date": "2026-02-28", "session": "Session 3"}
    解析失败时返回空字典。
    """
    body = data.get("body", data)
    gp = body.get("grading_period", {})
    if not gp:
        return {}
    title = gp.get("title", "") or gp.get("aria_label", "")
    if not title:
        return {}
    # 匹配 "M/DD/YY - M/DD/YY" 或 "M/DD/YY – M/DD/YY"（含破折号变体）
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2})\s*[-\u2013]\s*(\d{1,2})/(\d{1,2})/(\d{2})', title)
    if not m:
        return {}

    def yy2yyyy(yy: str) -> int:
        y = int(yy)
        return 2000 + y if y < 50 else 1900 + y

    start_str = f"{yy2yyyy(m.group(3))}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    end_str   = f"{yy2yyyy(m.group(6))}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"
    session_name = title.split(":")[0].strip() if ":" in title else title.strip()
    return {"start_date": start_str, "end_date": end_str, "session": session_name}


def parse_gradebook(data: dict, section_nid: str, course_name: str = "",
                    category_weights: dict = None) -> list[dict]:
    """
    返回 list of flat dicts，每条 = 一个 (student, assignment)。
    键名直接对应飞书字段名。
    """
    # API 响应包在 {"response_code": 200, "body": {...}} 里
    if "body" in data:
        data = data["body"]

    if not data.get("user_data"):
        print(f"  [debug] user_data 为空，API 顶层 keys: {list(data.keys())}")

    grade_item_data  = data.get("grade_item_data") or {}
    grades_by_uid    = data.get("grades") or {}
    user_data        = data.get("user_data") or {}
    grading_categories = {
        str(c["id"]): c.get("title", "")
        for c in (data.get("grading_categories") or [])
        if c["id"] not in ("all", "summary")
    }

    # 构建大小写不敏感的权重查找表，规避 gradesetup HTML 与 API 返回的分类名细微差异
    _cat_w = {k.strip().lower(): v for k, v in (category_weights or {}).items()}

    print(f"  [debug] user_data: {len(user_data)} 人, grade_item_data: {len(grade_item_data)} 项")

    # Debug：打印第一个学生的 grades 结构，帮助诊断总成绩为空的问题
    _debug_printed = False
    rows = []
    for uid, student in user_data.items():
        student_name    = student.get("name", "")
        overall_numeric = None
        grades_in_user  = student.get("grades") or {}

        if not _debug_printed:
            print(f"  [debug] grades keys in user_data sample: {list(grades_in_user.keys())[:10]}")
            overall_sample = grades_in_user.get("overall") or grades_in_user.get("all") or {}
            print(f"  [debug] overall/all sample: {str(overall_sample)[:200]}")
            _debug_printed = True

        # 兼容 "overall" 和 "all" 两种 key（Schoology API 版本差异）
        overall_raw = grades_in_user.get("overall") or grades_in_user.get("all") or {}
        if isinstance(overall_raw, dict):
            overall_numeric = overall_raw.get("numeric")

        student_grades = grades_by_uid.get(uid, {})

        for nid, item in grade_item_data.items():
            # 只处理真实的作业列（排除汇总列）
            if item.get("is_grade_column") or item.get("exclude_from_grade"):
                continue

            grade_entry = student_grades.get(nid, {})
            grade_val   = grade_entry.get("grade")        # float 或 None
            exception   = grade_entry.get("exception", 0) # 0=正常, 1=豁免 …
            submission  = grade_entry.get("submission", "") # "drop"=已提交
            comment_obj = grade_entry.get("comment") or {}
            comment_text = comment_obj.get("text", "") if isinstance(comment_obj, dict) else ""

            max_points  = item.get("max_points") or 0
            pct = round(grade_val / max_points * 100, 1) if (grade_val is not None and max_points) else None

            category_id    = str(item.get("grading_category_id", ""))
            category_title  = grading_categories.get(category_id, item.get("category_title", ""))
            # 大小写不敏感匹配，避免 gradesetup HTML 与 API 分类名细微差异导致权重丢失
            category_weight = _cat_w.get(category_title.strip().lower()) if _cat_w else None
            if category_weights and category_title and category_weight is None:
                print(f"  [debug] 分类权重未匹配: API分类名={category_title!r}, "
                      f"gradesetup已有keys={list(category_weights.keys())[:5]}")

            rows.append({
                "学生姓名":   student_name,
                "学生UID":    uid,
                "课程名":     course_name,
                "SectionNID": section_nid,
                "作业NID":    nid,
                "作业名":     item.get("title", ""),
                "分类":       category_title,
                "分类权重%":  category_weight,
                "评分维度":   item.get("alignments", ""),
                "得分":       grade_val,
                "满分":       max_points,
                "得分率":     pct,
                "截止日期":   item.get("due_date_text", ""),
                "已提交":     "✓" if submission == "drop" else ("豁免" if exception else ""),
                "老师评语":   comment_text,
                "课程总分%":  round(overall_numeric, 2) if overall_numeric is not None else None,
                # 唯一键，用于飞书 upsert 查重
                "_key":       f"{uid}_{nid}",
            })

    return rows


# ──────────────────────────────────────────────
# 飞书：Token
# ──────────────────────────────────────────────

def get_feishu_token(app_id: str, app_secret: str) -> str:
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"飞书 Token 获取失败: {resp.text}")
    return data["tenant_access_token"]


# ──────────────────────────────────────────────
# 飞书：读取现有记录（用于判断 insert vs update）
# ──────────────────────────────────────────────

def fetch_existing_records(token: str, app_token: str, table_id: str) -> dict:
    """返回 {_key: (record_id, section_nid)} 映射，用于 upsert。"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    existing = {}
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0:
            print(f"  [警告] 读取现有记录失败: {resp}")
            break
        for item in resp.get("data", {}).get("items", []):
            key = item.get("fields", {}).get("_key", "")
            nid = str(item.get("fields", {}).get("SectionNID", "")).strip()
            if key:
                existing[key] = (item["record_id"], nid)
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp["data"].get("page_token")
    return existing


# ──────────────────────────────────────────────
# 飞书：批量写入（insert / update）
# ──────────────────────────────────────────────

def build_feishu_fields(row: dict) -> dict:
    """把行数据转成飞书字段，过滤掉 None 和内部字段。"""
    skip = {"_key"}
    fields = {}
    for k, v in row.items():
        if k in skip:
            continue
        if v is None or v == "":
            continue
        fields[k] = v
    # 飞书数字字段不能是 Python float，要显式 float
    for num_key in ("得分", "满分", "得分率", "课程总分%", "分类权重%"):
        if num_key in fields and isinstance(fields[num_key], (int, float)):
            fields[num_key] = float(fields[num_key])
    # 飞书日期字段须为 Unix 毫秒时间戳
    if "截止日期" in fields:
        try:
            dt = datetime.strptime(fields["截止日期"].strip(), "%b %d, %Y at %I:%M %p")
            fields["截止日期"] = calendar.timegm(dt.timetuple()) * 1000
        except Exception:
            del fields["截止日期"]
    return fields


def batch_upsert(token: str, app_token: str, table_id: str,
                 rows: list[dict], existing: dict) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    to_insert = []
    to_update = []   # list of (record_id, fields)
    current_keys = set()
    # 本次爬取涉及的 section NIDs（只删这些 section 内消失的行，不碰其他 section）
    current_nids = {str(row.get("SectionNID", "")).strip() for row in rows}

    for row in rows:
        key    = row["_key"]
        fields = build_feishu_fields(row)
        fields["_key"] = key   # 保留 _key 供下次查重
        current_keys.add(key)

        if key in existing:
            record_id, _ = existing[key]
            to_update.append((record_id, fields))
        else:
            to_insert.append(fields)

    # ── delete：只删本次爬取的 section 内已消失的作业行 ──
    # 其他 section（如上学期）的行保持不动
    to_delete = [
        existing[k][0] for k in existing
        if k not in current_keys and existing[k][1] in current_nids
    ]
    chunk = 100
    if to_delete:
        del_url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
                   f"/{app_token}/tables/{table_id}/records/batch_delete")
        for i in range(0, len(to_delete), chunk):
            batch = to_delete[i:i+chunk]
            resp = requests.post(del_url, headers=headers, json={"records": batch})
            rj = resp.json()
            if rj.get("code") == 0:
                print(f"  ✓ 删除 {len(batch)} 条（作业已在 Schoology 移除）")
            else:
                print(f"  ✗ 删除失败: {rj}")
            time.sleep(0.3)

    # ── insert ──
    for i in range(0, len(to_insert), chunk):
        batch = to_insert[i:i+chunk]
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
               f"/{app_token}/tables/{table_id}/records/batch_create")
        resp = requests.post(url, headers=headers,
                             json={"records": [{"fields": f} for f in batch]})
        rj = resp.json()
        if rj.get("code") == 0:
            print(f"  ✓ 新增 {len(batch)} 条")
        else:
            print(f"  ✗ 新增失败: {rj}")
        time.sleep(0.3)

    # ── update ──
    for i in range(0, len(to_update), chunk):
        batch = to_update[i:i+chunk]
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
               f"/{app_token}/tables/{table_id}/records/batch_update")
        payload = {"records": [{"record_id": rid, "fields": f} for rid, f in batch]}
        resp = requests.post(url, headers=headers, json=payload)
        rj = resp.json()
        if rj.get("code") == 0:
            print(f"  ✓ 更新 {len(batch)} 条")
        else:
            print(f"  ✗ 更新失败: {rj}")
        time.sleep(0.3)



# ──────────────────────────────────────────────
# 飞书：同步选课到花名册 S1～S6 所属课程字段
# ──────────────────────────────────────────────

def parse_sem_short(title: str) -> str:
    """从 section 标题提取学期短码，如 'ESL Level 5: Section 2526S4N' → 'S4'。"""
    m = re.search(r'\d{4}(S\d)N', title)
    return m.group(1) if m else ""


def parse_semester_label(title: str) -> str:
    """从 section 标题提取完整学期标签，如 'ESL Level 5: Section 2526S4N' → '2025-S4'。"""
    m = re.search(r'(\d{2})(\d{2})(S\d)N', title)
    if not m:
        return ""
    year = "20" + m.group(1)   # 25 → 2025
    sem  = m.group(3)           # S4
    return f"{year}-{sem}"


def normalize_semester_value(raw) -> str:
    """归一化学期标签，去重脏值如 ['2025-S4', '2025-S4'] / '2025-S4,2025-S4'。"""
    if raw is None:
        return ""

    values = raw if isinstance(raw, list) else [raw]
    cleaned = []
    seen = set()
    for value in values:
        parts = re.split(r"[,\n]+", str(value or ""))
        for part in parts:
            sem = part.strip()
            if not sem:
                continue
            m = re.search(r"\d{4}-S\d+", sem, re.IGNORECASE)
            sem = m.group(0).upper() if m else sem
            if sem not in seen:
                seen.add(sem)
                cleaned.append(sem)

    if not cleaned:
        return ""
    return cleaned[0]


def normalize_assignment_name(raw) -> str:
    """标准化作业名，尽量让通知文案与 gradebook 标题能稳定匹配。"""
    text = str(raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def sync_enrollment_to_roster(
    token: str, app_token: str, roster_table_id: str,
    enrollment_by_sem: dict,  # {sem_short: {student_name: set(course_name)}}
):
    """把选课写入花名册 S1～S6 所属课程文本字段（每学期覆盖，不跨学期混淆）。"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{roster_table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}

    # 拉取花名册全量
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0:
            print(f"  [警告] 读取花名册失败: {resp}")
            return
        for item in resp.get("data", {}).get("items", []):
            records.append(item)
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp["data"].get("page_token")

    # 建索引：{姓名: record_id}
    roster_index = {
        str(item.get("fields", {}).get("学生姓名", "")).strip(): item["record_id"]
        for item in records
        if str(item.get("fields", {}).get("学生姓名", "")).strip()
    }
    all_names = set(roster_index.keys())

    # 按学期构建每个学生的更新 payload
    # {record_id: {field: value}}
    updates = {}
    for sem_short, name_courses in enrollment_by_sem.items():
        field = f"{sem_short}所属课程"
        # 在册学生：写入课程；不在该学期的学生：清空（覆盖旧数据）
        for name in all_names:
            rid = roster_index[name]
            updates.setdefault(rid, {})
            if name in name_courses:
                updates[rid][field] = "\n".join(sorted(name_courses[name]))
            else:
                updates[rid][field] = ""

    if not updates:
        print("  选课同步：无数据")
        return

    to_update = [{"record_id": rid, "fields": fields} for rid, fields in updates.items()]
    upd_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{roster_table_id}/records/batch_update"
    for i in range(0, len(to_update), 100):
        batch = to_update[i:i + 100]
        resp = requests.post(upd_url, json={"records": batch}, headers=headers).json()
        if resp.get("code") != 0:
            print(f"  [警告] 花名册选课更新失败: {resp.get('msg')}")
    print(f"  选课同步完成：{len(to_update)} 名学生，学期={sorted(enrollment_by_sem.keys())}")


# ──────────────────────────────────────────────
# 飞书：同步更新作业库
# ──────────────────────────────────────────────

def fetch_all_lib_records(token: str, app_token: str, lib_table_id: str) -> list:
    """拉取作业库全量记录，返回 items 列表。"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{lib_table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0:
            print(f"  [警告] 拉取作业库失败: {resp}")
            break
        data = resp.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


def update_lib_from_gradebook(token: str, app_token: str, lib_table_id: str,
                               all_rows: list) -> None:
    """
    根据 gradebook 里的作业，在作业库中标记为 🔥 极其重要、补全截止日期，并写入学期标签。
    匹配策略：gradebook 的 作业NID 对应作业库的 作业链接 中的数字 ID。
    已标记为 🚫 忽略 的记录不覆盖。
    """
    current_semester = normalize_semester_value(os.environ.get("CURRENT_SEMESTER", ""))
    # 1. 从 all_rows 收集 {nid: {due_ms, semester, assignment_name, course_name}}。
    # 学期优先用 section 标题里解析出的行级学期；截止日期去重后取最早。
    nid_meta: dict[str, dict] = {}
    for row in all_rows:
        nid = str(row.get("作业NID", "")).strip()
        if not nid:
            continue
        meta = nid_meta.setdefault(nid, {
            "due_ms": None,
            "semester": "",
            "assignment_name": "",
            "course_name": "",
        })

        row_semester = normalize_semester_value(row.get("学期", ""))
        if row_semester and not meta["semester"]:
            meta["semester"] = row_semester
        assignment_name = str(row.get("作业名", "")).strip()
        if assignment_name and not meta["assignment_name"]:
            meta["assignment_name"] = assignment_name
        course_name = str(row.get("课程名", "")).strip()
        if course_name and not meta["course_name"]:
            meta["course_name"] = course_name

        due_str = str(row.get("截止日期", "")).strip()
        if not due_str:
            continue
        try:
            dt = datetime.strptime(due_str, "%b %d, %Y at %I:%M %p")
            due_ms = calendar.timegm(dt.timetuple()) * 1000
        except Exception:
            continue
        if meta["due_ms"] is None or due_ms < meta["due_ms"]:
            meta["due_ms"] = due_ms

    if not nid_meta:
        print("  [更新作业库] 无有效作业 NID 元数据，跳过")
        return

    # 2. 拉取作业库全量，构建 NID → (record_id, nature) 映射
    print("\n读取作业库全量记录（用于同步 🔥 极其重要）...")
    lib_records = fetch_all_lib_records(token, app_token, lib_table_id)
    print(f"  作业库记录数: {len(lib_records)}")

    nid_to_record: dict[str, tuple] = {}
    fallback_by_name_course_sem: dict[tuple[str, str, str], list] = {}
    fallback_by_name_course: dict[tuple[str, str], list] = {}
    for rec in lib_records:
        rec_id = rec.get("record_id", "")
        f = rec.get("fields", {})
        raw_link = f.get("作业链接", "")
        if isinstance(raw_link, dict):
            link_str = str(raw_link.get("link", "") or raw_link.get("text", "")).strip()
        else:
            link_str = str(raw_link or "").strip()
        nature = str(f.get("作业性质", "")).strip()
        semester = normalize_semester_value(f.get("学期", ""))
        course_name = str(f.get("所属课程", "")).strip()
        assignment_name = str(f.get("作业名称", "")).strip()
        record_meta = {
            "record_id": rec_id,
            "nature": nature,
            "semester": semester,
            "course_name": course_name,
            "assignment_name": assignment_name,
        }

        if link_str:
            m = re.search(r'/(?:assignment|assessment|discussion)/(\d+)', link_str)
            if m:
                nid = m.group(1)
                if nid not in nid_to_record:
                    nid_to_record[nid] = record_meta

        normalized_name = normalize_assignment_name(assignment_name)
        if normalized_name and course_name:
            fallback_by_name_course.setdefault((normalized_name, course_name), []).append(record_meta)
            if semester:
                fallback_by_name_course_sem.setdefault((normalized_name, course_name, semester), []).append(record_meta)

    # 3. 构建更新列表（匹配到的 + 排除 🚫 忽略）
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    to_update = []
    skipped_ignore = 0
    semester_fixed = 0
    fallback_matched = 0
    ambiguous_fallback = 0
    for nid, meta in nid_meta.items():
        record_meta = nid_to_record.get(nid)
        if not record_meta:
            norm_name = normalize_assignment_name(meta.get("assignment_name", ""))
            course_name = str(meta.get("course_name", "")).strip()
            semester = meta.get("semester") or current_semester
            candidates = []
            if norm_name and course_name and semester:
                candidates = fallback_by_name_course_sem.get((norm_name, course_name, semester), [])
            if not candidates and norm_name and course_name:
                candidates = fallback_by_name_course.get((norm_name, course_name), [])
            if len(candidates) == 1:
                record_meta = candidates[0]
                fallback_matched += 1
            elif len(candidates) > 1:
                ambiguous_fallback += 1
                print(f"  [更新作业库] 名称兜底匹配歧义，跳过: {meta.get('assignment_name', '')} | {course_name} | {semester}")
                continue
            else:
                continue

        rec_id = record_meta["record_id"]
        nature = record_meta["nature"]
        existing_semester = record_meta["semester"]
        if nature == "🚫 忽略":
            skipped_ignore += 1
            continue
        fields = {
            "作业性质": "🔥 极其重要",
        }
        due_ms = meta.get("due_ms")
        if due_ms is not None:
            fields["截止日期"] = due_ms

        semester = meta.get("semester") or current_semester
        if semester:
            fields["学期"] = semester
            if semester != existing_semester:
                semester_fixed += 1
        to_update.append({"record_id": rec_id, "fields": fields})

    if skipped_ignore:
        print(f"  跳过 🚫 忽略 记录: {skipped_ignore} 条")

    if not to_update:
        print("  [更新作业库] 无匹配记录，跳过")
        return

    # 4. 批量更新
    chunk = 100
    updated = 0
    update_url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps"
                  f"/{app_token}/tables/{lib_table_id}/records/batch_update")
    for i in range(0, len(to_update), chunk):
        batch = to_update[i:i+chunk]
        resp = requests.post(update_url, headers=headers,
                             json={"records": batch}).json()
        if resp.get("code") == 0:
            updated += len(batch)
        else:
            print(f"  ✗ 更新作业库失败: {resp}")
        time.sleep(0.3)

    print(f"  ✓ 更新作业库 {updated} 条")
    if semester_fixed:
        print(f"  ✓ 规范化/补写学期 {semester_fixed} 条")
    if fallback_matched:
        print(f"  ✓ 名称兜底匹配并标记极其重要 {fallback_matched} 条")
    if ambiguous_fallback:
        print(f"  [提示] 名称兜底匹配存在歧义 {ambiguous_fallback} 条，已跳过避免误标")


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def _fetch_course_mapping(token: str, app_token: str, table_id: str) -> dict:
    """从飞书系统配置表读取 course_mapping，失败时返回 None（调用方使用 DEFAULT_COURSE_MAPPING）。"""
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    headers = {"Authorization": f"Bearer {token}"}
    flt = json.dumps({"conjunction":"and","conditions":[{"field_name":"配置键","operator":"is","value":["course_mapping"]}]})
    r = requests.get(f"{base}/records", params={"filter": flt, "page_size": 5}, headers=headers)
    items = r.json().get("data", {}).get("items", [])
    if not items:
        return None
    raw = items[0]["fields"].get("配置值", "")
    text = raw if isinstance(raw, str) else (raw[0].get("text", "") if raw else "")
    return json.loads(text)


def _upsert_config(token: str, app_token: str, table_id: str, key: str, value: str):
    """在系统配置表中 upsert 一行 (配置键=key, 配置值=value)。
    全量拉取后在 Python 端匹配，避免飞书文本字段 filter 不稳定导致重复创建。
    """
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 全量拉取（配置表条数极少，通常 < 20 条）
    all_items = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{base}/records", params=params, headers=headers).json()
        all_items.extend(r.get("data", {}).get("items", []))
        if not r.get("data", {}).get("has_more"):
            break
        page_token = r["data"]["page_token"]
    # Python 端匹配 配置键
    matched = [it for it in all_items
               if str(it["fields"].get("配置键", "")).strip() == key]
    payload = {"fields": {"配置键": key, "配置值": value}}
    if matched:
        record_id = matched[0]["record_id"]
        requests.put(f"{base}/records/{record_id}", json=payload, headers=headers)
        print(f"  [config] 更新 '{key}'")
    else:
        requests.post(f"{base}/records", json=payload, headers=headers)
        print(f"  [config] 新建 '{key}'")


def main():
    print("=" * 55)
    print("  Gradebook Scraper 启动")
    print("=" * 55)

    cfg = get_env_config()
    # SCHOOLOGY_SECTION_NIDS 格式：{"section_nid": "课程名", ...}
    # 清洗 GitHub Secret 可能混入的不可见控制字符
    nids_raw = re.sub(r'[\x00-\x1f\x7f]', '', cfg["SCHOOLOGY_SECTION_NIDS"])
    sections_raw: dict = json.loads(nids_raw)

    cookies_raw = json.loads(cfg["SCHOOLOGY_COOKIES"])

    # 建立 Schoology 请求会话
    session = build_session(cookies_raw)
    verify_cookies(session)  # Cookie 过期时立即告警并终止

    # 获取飞书 Token
    token = get_feishu_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])

    # 读取课程名映射：以代码内置映射为基础，飞书配置表的条目优先覆盖
    config_table_id = cfg.get("FEISHU_CONFIG_TABLE_ID", "").strip()
    course_mapping = dict(DEFAULT_COURSE_MAPPING)   # 始终以内置映射为底
    if config_table_id:
        try:
            feishu_mapping = _fetch_course_mapping(token, cfg["FEISHU_APP_TOKEN"], config_table_id)
            if feishu_mapping:
                course_mapping.update(feishu_mapping)   # 飞书条目覆盖内置条目
                print(f"✅ 课程名映射：内置 {len(DEFAULT_COURSE_MAPPING)} 条 + 飞书 {len(feishu_mapping)} 条覆盖")
            else:
                print(f"  [提示] 飞书课程名映射为空，仅使用内置映射（{len(course_mapping)} 条）")
        except Exception as e:
            print(f"  [警告] 飞书课程映射读取失败，仅使用内置映射: {e}")
    else:
        print(f"  [提示] 使用内置课程名映射（{len(course_mapping)} 条）")

    sections = {
        nid: course_mapping.get(
            re.sub(r'\s+', ' ', name.split(":")[0]).lower().strip(),  # 取冒号前的课程名做映射
            name.split(":")[0].strip()                                  # 映射失败时也只保留课程名
        )
        for nid, name in sections_raw.items()
    }
    print(f"课程 Section 数量: {len(sections)}")

    # NID → 学期短码（S1～S6），从标题解析
    nid_to_sem = {nid: parse_sem_short(title) for nid, title in sections_raw.items()}
    # NID → 完整学期标签（如 2025-S4），供写入飞书 Gradebook "学期" 字段
    nid_to_semester_label = {nid: parse_semester_label(title) for nid, title in sections_raw.items()}

    # 校验 NID 格式：Schoology NID 应为纯数字，否则极可能是 JSON 里 NID 和课程名顺序写反
    for nid in list(sections.keys()):
        if not re.match(r'^\d+$', str(nid).strip()):
            print(f"  [错误] NID 格式异常: {nid!r}（应为纯数字）。"
                  f"请检查 SCHOOLOGY_SECTION_NIDS 是否把课程名和 NID 的顺序写反了，"
                  f"正确格式: {{\"NID\": \"课程名: Section XXXX\"}}。跳过此 Section。")
            del sections[nid]

    # 读取飞书现有记录（用于 upsert）
    print("\n读取飞书 Gradebook 表现有记录...")
    existing = fetch_existing_records(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"]
    )
    print(f"  现有记录数: {len(existing)}")

    all_rows = []
    gp_info = {}
    all_cat_weights = {}   # nid → {category_title: weight}，汇总后写 category_weights.json
    section_gp = {}        # nid → gp_info，每个 section 独立学期信息
    enrollment_by_sem = {} # {sem_short: {student_name: set(course_name)}}，写花名册用
    for nid, course_name in sections.items():
        print(f"\n── {course_name} ({nid}) ──")
        try:
            category_weights = fetch_gradesetup_weights(session, nid)
            data = fetch_gradebook(session, nid)
            rows = parse_gradebook(data, nid, course_name, category_weights)
            # 追加学期字段（从 section 标题解析，如 2025-S4）
            sem_label = nid_to_semester_label.get(str(nid), "")
            if sem_label:
                for row in rows:
                    row["学期"] = sem_label
            print(f"  解析到 {len(rows)} 条 (学生×作业)")
            all_rows.extend(rows)
            # 从 user_data 收集选课（无论有没有 grade_item_data 都有学生名单）
            # API 响应可能包在 body 里，与 parse_gradebook 保持一致
            user_data_src = data.get("body", data)
            sem_short = nid_to_sem.get(str(nid), "")
            if sem_short:
                sem_bucket = enrollment_by_sem.setdefault(sem_short, {})
                for uid, student in (user_data_src.get("user_data") or {}).items():
                    name = str(student.get("name", "")).strip()
                    if name:
                        sem_bucket.setdefault(name, set()).add(course_name)
            else:
                print(f"  [提示] 无法解析 {nid} 的学期短码，跳过选课同步")
            # 构建 title→weight 映射，供 build_student_summary.py 使用
            # fetch_gradesetup_weights 现在直接返回 {title: weight}，可直接存储
            if category_weights:
                all_cat_weights[nid] = category_weights
            # 每个 section 单独提取学期信息
            gp = parse_grading_period_dates(data)
            if gp:
                section_gp[nid] = gp
                print(f"  学期: {gp['session']}  {gp['start_date']} → {gp['end_date']}")
                if not gp_info:
                    gp_info = gp
        except Exception as e:
            print(f"  [错误] {e}")

    print(f"\n共 {len(all_rows)} 条，开始写入飞书...")
    batch_upsert(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"],
        all_rows, existing
    )

    # 选课同步到花名册（基于 user_data，即使 grade_item_data 为空也能覆盖）
    roster_table_id = cfg.get("FEISHU_ROSTER_TABLE_ID", "").strip()
    if roster_table_id and enrollment_by_sem:
        print(f"\n>>> 同步选课到花名册（{sum(len(v) for v in enrollment_by_sem.values())} 名学生，学期={sorted(enrollment_by_sem.keys())}）...")
        sync_enrollment_to_roster(token, cfg["FEISHU_APP_TOKEN"], roster_table_id, enrollment_by_sem)
    elif not roster_table_id:
        print("\n  [提示] FEISHU_ROSTER_TABLE_ID 未设置，跳过选课同步")

    # 分类权重写入本地文件，供 build_student_summary.py 读取
    if all_cat_weights:
        cw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_weights.json")
        try:
            with open(cw_path, "w", encoding="utf-8") as f:
                json.dump(all_cat_weights, f, ensure_ascii=False)
            total_cats = sum(len(v) for v in all_cat_weights.values())
            print(f">>> 分类权重已写入: {cw_path}（{len(all_cat_weights)} 个 section，{total_cats} 个分类）")
        except Exception as e:
            print(f"  [警告] 分类权重写入失败: {e}")

    # Section 学期映射写入本地文件，供 build_student_summary.py 区分多学期同名课程
    if section_gp:
        ss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "section_semesters.json")
        try:
            with open(ss_path, "w", encoding="utf-8") as f:
                json.dump(section_gp, f, ensure_ascii=False)
            print(f">>> Section 学期映射已写入: {ss_path}（{len(section_gp)} 个 section）")
        except Exception as e:
            print(f"  [警告] Section 学期映射写入失败: {e}")

    # 学期元数据写入本地文件，供 build_student_summary.py 读取
    if gp_info:
        gp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grading_period.json")
        try:
            with open(gp_path, "w", encoding="utf-8") as f:
                json.dump(gp_info, f, ensure_ascii=False)
            print(f">>> 学期元数据已写入: {gp_path}")
        except Exception as e:
            print(f"  [警告] 学期元数据写入失败: {e}")

        # 同时写入飞书系统配置表（供 server.js 读取，避免依赖文件/环境变量）
        config_table_id = cfg.get("FEISHU_CONFIG_TABLE_ID", "").strip()
        if config_table_id:
            try:
                _upsert_config(token, cfg["FEISHU_APP_TOKEN"], config_table_id,
                               "grading_period", json.dumps(gp_info, ensure_ascii=False))
                print(f">>> 学期元数据已写入飞书系统配置表")
            except Exception as e:
                print(f"  [警告] 学期元数据写入飞书失败: {e}")
        else:
            print("  [提示] FEISHU_CONFIG_TABLE_ID 未设置，跳过写入飞书配置表")

    # 可选：同步更新作业库（需设置 FEISHU_LIB_TABLE_ID）
    lib_table_id = cfg.get("FEISHU_LIB_TABLE_ID", "").strip()
    if lib_table_id:
        update_lib_from_gradebook(
            token, cfg["FEISHU_APP_TOKEN"], lib_table_id, all_rows
        )
    else:
        print("\n[跳过] FEISHU_LIB_TABLE_ID 未设置，不更新作业库")

    print("\n✅ Gradebook 同步完成")


if __name__ == "__main__":
    main()
