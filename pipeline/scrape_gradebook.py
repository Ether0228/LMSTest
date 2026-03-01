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
    "grade 11 physics":               "SPH3U",
    "grade 12 physics":               "SPH4U",
    "grade 12 data management":       "MDM4U",
    "grade 12 advanced functions":    "MHF4U",
    "grade 11 functions":             "MCR3U",
    "grade 12 calculus & vectors":    "MCV4U",
    "grade 12 canadian and world issues": "CGW4U",
    "grade 12 english":               "ENG4U",
    "grade 11 english":               "ENG3U",
    "grade 12 nutrition & health":    "HFA4U",
    "grade 12 visual arts":           "AVI4M",
    "g10 canadian history since wwi": "CHC2D",
    "esl level 5":                    "ESLEO",
    "esl level 4":                    "ESLDO",
    "esl level 3":                    "ESLCO",
    "esl level 2":                    "ESLBO",
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
    optional_keys = ["FEISHU_LIB_TABLE_ID", "FEISHU_CONFIG_TABLE_ID"]
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
    resp = session.get(url, timeout=30, allow_redirects=True)
    print(f"  ← HTTP {resp.status_code}  final_url={resp.url}")
    if not resp.text.strip():
        raise ValueError("响应为空（cookies 可能已过期，请更新 SCHOOLOGY_COOKIES）")
    if resp.text.strip().startswith("<"):
        # 返回了 HTML，说明被重定向到登录页
        raise ValueError(f"返回 HTML 而非 JSON（被重定向到登录页）: {resp.text[:200]}")
    return resp.json()


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


def parse_gradebook(data: dict, section_nid: str, course_name: str = "") -> list[dict]:
    """
    返回 list of flat dicts，每条 = 一个 (student, assignment)。
    键名直接对应飞书字段名。
    """
    # API 响应包在 {"response_code": 200, "body": {...}} 里
    if "body" in data:
        data = data["body"]

    grade_item_data  = data.get("grade_item_data", {})
    grades_by_uid    = data.get("grades", {})
    user_data        = data.get("user_data", {})
    grading_categories = {
        str(c["id"]): {"title": c.get("title", ""), "weight": c.get("weight")}
        for c in data.get("grading_categories", [])
        if c["id"] not in ("all", "summary")
    }

    print(f"  [debug] user_data: {len(user_data)} 人, grade_item_data: {len(grade_item_data)} 项")

    rows = []
    for uid, student in user_data.items():
        student_name    = student.get("name", "")
        overall_numeric = None
        overall_raw = (student.get("grades") or {}).get("overall") or {}
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
            cat_info       = grading_categories.get(category_id, {})
            category_title  = cat_info.get("title", item.get("category_title", "")) if isinstance(cat_info, dict) else str(cat_info)
            category_weight = cat_info.get("weight") if isinstance(cat_info, dict) else None

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
    """返回 {_key: record_id} 映射，用于 upsert。"""
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
            if key:
                existing[key] = item["record_id"]
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

    for row in rows:
        key    = row["_key"]
        fields = build_feishu_fields(row)
        fields["_key"] = key   # 保留 _key 供下次查重
        current_keys.add(key)

        if key in existing:
            to_update.append((existing[key], fields))
        else:
            to_insert.append(fields)

    # ── delete（Schoology 已删除的作业） ──
    to_delete = [existing[k] for k in existing if k not in current_keys]
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
    current_semester = os.environ.get("CURRENT_SEMESTER", "").strip()
    # 1. 从 all_rows 收集 {nid: due_date_ms}（去重，取最早截止日期）
    nid_due: dict[str, int] = {}
    for row in all_rows:
        nid = str(row.get("作业NID", "")).strip()
        due_str = str(row.get("截止日期", "")).strip()
        if not nid or not due_str:
            continue
        try:
            dt = datetime.strptime(due_str, "%b %d, %Y at %I:%M %p")
            due_ms = calendar.timegm(dt.timetuple()) * 1000
        except Exception:
            continue
        if nid not in nid_due or due_ms < nid_due[nid]:
            nid_due[nid] = due_ms

    if not nid_due:
        print("  [更新作业库] 无有效作业 NID，跳过")
        return

    # 2. 拉取作业库全量，构建 NID → (record_id, nature) 映射
    print("\n读取作业库全量记录（用于同步 🔥 极其重要）...")
    lib_records = fetch_all_lib_records(token, app_token, lib_table_id)
    print(f"  作业库记录数: {len(lib_records)}")

    nid_to_record: dict[str, tuple] = {}
    for rec in lib_records:
        rec_id = rec.get("record_id", "")
        f = rec.get("fields", {})
        raw_link = f.get("作业链接", "")
        if isinstance(raw_link, dict):
            link_str = str(raw_link.get("link", "") or raw_link.get("text", "")).strip()
        else:
            link_str = str(raw_link or "").strip()
        if not link_str:
            continue
        m = re.search(r'/(?:assignment|assessment|discussion)/(\d+)', link_str)
        if not m:
            continue
        nid = m.group(1)
        if nid not in nid_to_record:
            nid_to_record[nid] = (rec_id, str(f.get("作业性质", "")).strip())

    # 3. 构建更新列表（匹配到的 + 排除 🚫 忽略）
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    to_update = []
    skipped_ignore = 0
    for nid, due_ms in nid_due.items():
        if nid not in nid_to_record:
            continue
        rec_id, nature = nid_to_record[nid]
        if nature == "🚫 忽略":
            skipped_ignore += 1
            continue
        fields = {
            "作业性质": "🔥 极其重要",
            "截止日期": due_ms,
        }
        if current_semester:
            fields["学期"] = current_semester
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
        nid: course_mapping.get(re.sub(r'\s+', ' ', name).lower().strip(), name)
        for nid, name in sections_raw.items()
    }
    print(f"课程 Section 数量: {len(sections)}")

    # 读取飞书现有记录（用于 upsert）
    print("\n读取飞书 Gradebook 表现有记录...")
    existing = fetch_existing_records(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"]
    )
    print(f"  现有记录数: {len(existing)}")

    all_rows = []
    gp_info = {}
    for nid, course_name in sections.items():
        print(f"\n── {course_name} ({nid}) ──")
        try:
            data = fetch_gradebook(session, nid)
            rows = parse_gradebook(data, nid, course_name)
            print(f"  解析到 {len(rows)} 条 (学生×作业)")
            all_rows.extend(rows)
            # 从第一个有效 section 提取学期日期
            if not gp_info:
                gp_info = parse_grading_period_dates(data)
                if gp_info:
                    print(f"  学期: {gp_info['session']}  {gp_info['start_date']} → {gp_info['end_date']}")
        except Exception as e:
            print(f"  [错误] {e}")

    print(f"\n共 {len(all_rows)} 条，开始写入飞书...")
    batch_upsert(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"],
        all_rows, existing
    )

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
