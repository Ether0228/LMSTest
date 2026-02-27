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
import requests
from datetime import datetime


BASE_URL = "https://queenscanada.schoology.com"


# ──────────────────────────────────────────────
# 配置读取
# ──────────────────────────────────────────────

def get_env_config():
    keys = [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN", "FEISHU_GRADEBOOK_TABLE_ID",
        "SCHOOLOGY_COOKIES", "SCHOOLOGY_SECTION_NIDS",
    ]
    cfg = {k: os.environ.get(k, "").strip() for k in keys}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise ValueError(f"缺少环境变量: {', '.join(missing)}")
    return cfg


# ──────────────────────────────────────────────
# Schoology：用 cookies 建 requests.Session
# ──────────────────────────────────────────────

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


def parse_gradebook(data: dict, section_nid: str, course_name: str = "") -> list[dict]:
    """
    返回 list of flat dicts，每条 = 一个 (student, assignment)。
    键名直接对应飞书字段名。
    """
    grade_item_data  = data.get("grade_item_data", {})
    grades_by_uid    = data.get("grades", {})          # grades[uid][nid]
    user_data        = data.get("user_data", {})
    grading_categories = {
        str(c["id"]): c["title"]
        for c in data.get("grading_categories", [])
        if c["id"] not in ("all", "summary")
    }

    # 调试：打印顶层结构
    print(f"  [debug] 顶层 keys: {list(data.keys())}")
    print(f"  [debug] user_data 数量: {len(user_data)}, grade_item_data 数量: {len(grade_item_data)}, grades 数量: {len(grades_by_uid)}")
    if user_data:
        sample_uid = next(iter(user_data))
        print(f"  [debug] user_data 示例 uid={sample_uid}: {list(user_data[sample_uid].keys())}")
    if grade_item_data:
        sample_nid = next(iter(grade_item_data))
        print(f"  [debug] grade_item_data 示例 nid={sample_nid}: {list(grade_item_data[sample_nid].keys())}")

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
            category_title = grading_categories.get(category_id, item.get("category_title", ""))

            rows.append({
                "学生姓名":   student_name,
                "学生UID":    uid,
                "课程名":     course_name,
                "SectionNID": section_nid,
                "作业NID":    nid,
                "作业名":     item.get("title", ""),
                "分类":       category_title,
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
    for num_key in ("得分", "满分", "得分率", "课程总分%"):
        if num_key in fields and isinstance(fields[num_key], (int, float)):
            fields[num_key] = float(fields[num_key])
    return fields


def batch_upsert(token: str, app_token: str, table_id: str,
                 rows: list[dict], existing: dict) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    to_insert = []
    to_update = []   # list of (record_id, fields)

    for row in rows:
        key    = row["_key"]
        fields = build_feishu_fields(row)
        fields["_key"] = key   # 保留 _key 供下次查重

        if key in existing:
            to_update.append((existing[key], fields))
        else:
            to_insert.append(fields)

    # ── insert ──
    chunk = 100
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
# 主流程
# ──────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Gradebook Scraper 启动")
    print("=" * 55)

    cfg = get_env_config()
    # SCHOOLOGY_SECTION_NIDS 格式：{"section_nid": "课程名", ...}
    # 清洗 GitHub Secret 可能混入的不可见控制字符
    nids_raw = re.sub(r'[\x00-\x1f\x7f]', '', cfg["SCHOOLOGY_SECTION_NIDS"])
    sections: dict = json.loads(nids_raw)
    cookies_raw  = json.loads(cfg["SCHOOLOGY_COOKIES"])

    print(f"课程 Section 数量: {len(sections)}")

    # 建立 Schoology 请求会话
    session = build_session(cookies_raw)

    # 获取飞书 Token
    token = get_feishu_token(cfg["FEISHU_APP_ID"], cfg["FEISHU_APP_SECRET"])

    # 读取飞书现有记录（用于 upsert）
    print("\n读取飞书 Gradebook 表现有记录...")
    existing = fetch_existing_records(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"]
    )
    print(f"  现有记录数: {len(existing)}")

    all_rows = []
    for nid, course_name in sections.items():
        print(f"\n── {course_name} ({nid}) ──")
        try:
            data = fetch_gradebook(session, nid)
            rows = parse_gradebook(data, nid, course_name)
            print(f"  解析到 {len(rows)} 条 (学生×作业)")
            all_rows.extend(rows)
        except Exception as e:
            print(f"  [错误] {e}")

    print(f"\n共 {len(all_rows)} 条，开始写入飞书...")
    batch_upsert(
        token, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"],
        all_rows, existing
    )

    print("\n✅ Gradebook 同步完成")


if __name__ == "__main__":
    main()
