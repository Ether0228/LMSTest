import os
import json
import requests
import time
import re
from datetime import datetime, timedelta


def get_current_week_start():
    """本周周一 00:00（pipeline 跑在 TZ=Asia/Shanghai 环境下）"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_submitted_at(value):
    """把各种格式的提交时间解析为 datetime，失败返回 None"""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000)
    for fmt in ["%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def is_aol(nature):
    """判断作业性质是否为 AoL（Assessment of Learning）"""
    n = str(nature).lower()
    return "aol" in n or "assessment of learning" in n


def get_env_config():
    keys = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN",
        "FEISHU_TABLE_ID",  # 提交记录表
        "FEISHU_ROSTER_TABLE_ID",  # 学生花名册
        "FEISHU_LIB_TABLE_ID",  # 作业库（用于补齐缺交作业名/链接）
        "FEISHU_MISSING_TABLE_ID",  # 缺交表
        "FEISHU_SUMMARY_TABLE_ID",  # 学生汇总表（新增）
    ]
    conf = {k: os.environ.get(k, "").strip() for k in keys}
    if not all(conf.values()):
        missing = [k for k, v in conf.items() if not v]
        raise ValueError(f"环境变量不完整，缺少: {', '.join(missing)}")
    return conf


def get_feishu_token(conf):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(
        url, json={"app_id": conf["FEISHU_APP_ID"], "app_secret": conf["FEISHU_APP_SECRET"]}
    ).json()
    token = resp.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"获取 tenant_access_token 失败: {resp}")
    return token


def fetch_all_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"拉取失败 table={table_id}: {resp}")
        data = resp.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
    return records


def batch_create(token, app_token, table_id, rows):
    if not rows:
        return
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    for i in range(0, len(rows), 100):
        payload = {"records": [{"fields": r} for r in rows[i : i + 100]]}
        resp = requests.post(url, json=payload, headers=headers).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"batch_create 失败: {resp}")


def batch_update(token, app_token, table_id, rows):
    if not rows:
        return
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    for i in range(0, len(rows), 100):
        payload = {"records": rows[i : i + 100]}
        resp = requests.post(url, json=payload, headers=headers).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"batch_update 失败: {resp}")


def chunk_text_json(obj, max_len=10000):
    text = json.dumps(obj, ensure_ascii=False)
    if len(text) <= max_len:
        return text
    # 防止单元格太长，截断近期提交
    if isinstance(obj, list):
        while len(text) > max_len and len(obj) > 5:
            obj = obj[: len(obj) - 5]
            text = json.dumps(obj, ensure_ascii=False)
    return text[:max_len]


def extract_linked_record_ids(value):
    """
    飞书关联字段在不同场景可能返回：
    1) ["recxxx", "recyyy"]
    2) [{"record_id":"recxxx"}, {"record_id":"recyyy"}]
    3) {"record_id":"recxxx"}
    4) "recxxx"
    统一抽取为 record_id 字符串列表。
    """
    if value is None:
        return []

    out = set()

    def visit(node):
        if node is None:
            return
        if isinstance(node, str):
            s = node.strip()
            if s.startswith("rec"):
                out.add(s)
            return
        if isinstance(node, list):
            for x in node:
                visit(x)
            return
        if isinstance(node, dict):
            # 常见形式：{"record_id":"rec..."} / {"record_ids":["rec..."]} / 嵌套结构
            for key in ("record_id", "recordId", "id"):
                val = node.get(key)
                if isinstance(val, str) and val.strip().startswith("rec"):
                    out.add(val.strip())
            for key in ("record_ids", "recordIds", "link_record_ids", "linkRecordIds"):
                val = node.get(key)
                if isinstance(val, list):
                    for rid in val:
                        if isinstance(rid, str) and rid.strip().startswith("rec"):
                            out.add(rid.strip())
            # 递归扫一遍，兼容未知嵌套
            for _, v in node.items():
                if isinstance(v, (dict, list)):
                    visit(v)

    visit(value)
    return list(out)


def normalize_link(v):
    if isinstance(v, dict):
        return str(v.get("link") or v.get("text") or "").strip()
    return str(v or "").strip()

def clean_schoology_url(url):
    if not url:
        return ""
    text = str(url).strip()
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', text)
    return match.group(1) if match else text


def build_assignment_lookup(lib_records):
    # rec_id -> {name, link, course}
    out = {}
    # clean_link -> {name, link, course}
    by_link = {}
    for rec in lib_records:
        rec_id = rec.get("record_id")
        f = rec.get("fields", {})
        item = {
            "name": str(f.get("作业名称", "")).strip(),
            "link": clean_schoology_url(normalize_link(f.get("作业链接"))),
            "course": str(f.get("所属课程", "")).strip(),
            "nature": str(f.get("作业性质", "")).strip(),
        }
        if rec_id:
            out[rec_id] = item
        link = item["link"]
        if link:
            by_link[link] = item
    return out, by_link


def build_summaries(roster, submissions, missing, assignment_lookup, assignment_by_link):
    # 1) 学生基础信息
    students = {}
    for r in roster:
        f = r.get("fields", {})
        name = str(f.get("学生姓名", "")).strip()
        if not name:
            continue
        courses = f.get("所属课程", [])
        if not isinstance(courses, list):
            courses = [courses] if courses else []
        students[name] = {
            "name": name,
            "roster_record_id": r.get("record_id"),
            "courses": courses,
            "submitted": [],
            "missing": [],
            "missing_items": [],
            "submitted_by_course": {},
            "expected_by_course": {},
            # 花名册额外字段（需在飞书花名册表中添加对应列）
            "school_year":   str(f.get("学年", "")).strip(),
            "semester_num":  str(f.get("学期号", "")).strip(),
            "osslt":         str(f.get("OSSLT状态", "")).strip(),
            "credits_earned": f.get("已获学分", ""),
            "credits_target": f.get("目标学分", ""),
            "notices_raw":   str(f.get("公告", "")).strip(),
        }

    # 1.5) 每个学生每科"应交总数"（基于作业库，忽略标记为🚫 忽略）
    lib_by_course = {}
    for _, item in assignment_lookup.items():
        course = (item.get("course") or "").strip()
        if not course:
            continue
        if item.get("nature") == "🚫 忽略":
            continue
        lib_by_course[course] = lib_by_course.get(course, 0) + 1
    for _, s in students.items():
        for course in s["courses"]:
            c = str(course).strip()
            if not c:
                continue
            s["expected_by_course"][c] = int(lib_by_course.get(c, 0))

    # 2) 提交记录聚合（按"学生姓名"文本）
    for s in submissions:
        f = s.get("fields", {})
        name = str(f.get("学生姓名", "")).strip()
        if not name or name not in students:
            continue
        linked_assignment_ids = extract_linked_record_ids(f.get("关联作业"))
        assignment = {}
        for a_id in linked_assignment_ids:
            assignment = assignment_lookup.get(a_id, {})
            if assignment:
                break
        if not assignment:
            assignment = assignment_by_link.get(clean_schoology_url(normalize_link(f.get("作业链接"))), {})
        course_name = assignment.get("course", "").strip() or "未分类"
        students[name]["submitted"].append(
            {
                "assignmentName": f.get("作业名称", ""),
                "status": f.get("提交状态", ""),
                "submittedAt": f.get("提交时间", ""),
                "link": (f.get("作业链接", {}) or {}).get("link", "")
                if isinstance(f.get("作业链接"), dict)
                else str(f.get("作业链接", "")),
                "course": course_name,
                "nature": assignment.get("nature", ""),
            }
        )
        sbc = students[name]["submitted_by_course"]
        sbc[course_name] = sbc.get(course_name, 0) + 1

    # 3) 缺交记录聚合（按"关联学生" record_id）
    roster_id_to_name = {
        v["roster_record_id"]: k for k, v in students.items() if v.get("roster_record_id")
    }
    missing_rows_total = 0
    missing_rows_with_link = 0
    missing_links_matched = 0
    missing_links_unmatched = 0

    for m in missing:
        missing_rows_total += 1
        f = m.get("fields", {})
        linked = extract_linked_record_ids(f.get("关联学生"))
        linked_assignment_ids = extract_linked_record_ids(f.get("关联作业"))
        if linked:
            missing_rows_with_link += 1
        assignment = {}
        for a_id in linked_assignment_ids:
            assignment = assignment_lookup.get(a_id, {})
            if assignment:
                break
        # 跳过在作业库中标记为"🚫 忽略"的作业
        if assignment.get("nature") == "🚫 忽略":
            continue
        course_name = str(f.get("所属课程", "")).strip() or assignment.get("course", "") or "未分类"
        assignment_name = assignment.get("name", "")
        assignment_link = assignment.get("link", "")
        for rid in linked:
            name = roster_id_to_name.get(rid)
            if not name:
                missing_links_unmatched += 1
                continue
            missing_links_matched += 1
            students[name]["missing"].append(
                {
                    "course": course_name,
                }
            )
            students[name]["missing_items"].append(
                {
                    "course": course_name,
                    "assignmentName": assignment_name,
                    "assignmentLink": assignment_link,
                    "nature": assignment.get("nature", ""),
                }
            )

    # 4) 汇总字段
    now_ms = int(time.time() * 1000)
    week_start = get_current_week_start()
    week_end   = week_start + timedelta(days=7)
    week_label = f"{week_start.month}/{week_start.day}-{week_end.month}/{week_end.day - 1}"

    rows = []
    for name, s in students.items():
        missing_by_course = {}
        for item in s["missing"]:
            c = item["course"]
            missing_by_course[c] = missing_by_course.get(c, 0) + 1
        all_courses = sorted(
            set(s["courses"])
            | set(s["submitted_by_course"].keys())
            | set(missing_by_course.keys())
            | set(s["expected_by_course"].keys())
        )

        # AoL 统计
        aol_submitted_by_course = {}
        for sub in s["submitted"]:
            if is_aol(sub.get("nature", "")):
                c = sub.get("course", "未分类")
                aol_submitted_by_course[c] = aol_submitted_by_course.get(c, 0) + 1

        aol_missing_by_course = {}
        for item in s["missing_items"]:
            if is_aol(item.get("nature", "")):
                c = item.get("course", "未分类")
                aol_missing_by_course[c] = aol_missing_by_course.get(c, 0) + 1

        course_progress = []
        for c in all_courses:
            expected_count = int(s["expected_by_course"].get(c, 0))
            missing_count = int(missing_by_course.get(c, 0))
            submitted_from_expected = max(expected_count - missing_count, 0) if expected_count > 0 else 0
            submitted_count = int(s["submitted_by_course"].get(c, submitted_from_expected))
            total = expected_count if expected_count > 0 else (submitted_count + missing_count)
            completion = round((submitted_count / total) * 100, 1) if total > 0 else 0.0
            course_progress.append(
                {
                    "course":         c,
                    "submittedCount": submitted_count,
                    "missingCount":   missing_count,
                    "completion":     completion,
                    "aolSubmitted":   aol_submitted_by_course.get(c, 0),
                    "aolMissing":     aol_missing_by_course.get(c, 0),
                }
            )

        submitted_sorted = sorted(
            s["submitted"], key=lambda x: str(x.get("submittedAt", "")), reverse=True
        )
        # 近期提交：本周（周一 00:00 到下周一 00:00）
        recent = [
            sub for sub in submitted_sorted
            if week_start <= (parse_submitted_at(sub.get("submittedAt")) or datetime.min) < week_end
        ]
        missing_items  = s["missing_items"]
        missing_total  = len(s["missing"])
        submitted_total = len(s["submitted"])

        recommendations = []
        if missing_total > 0:
            recommendations.append(
                {"title": "优先处理缺交：复活与翻盘", "anchorText": "4.8 危机关：复活与翻盘"}
            )
            recommendations.append(
                {"title": "用 Rubric 直接提分", "anchorText": "4.4 作业关：Rubric 狙击手"}
            )
        if missing_total >= 3:
            recommendations.append(
                {"title": "建立每日循环，止住连锁迟交", "anchorText": "4.2 每日循环 Daily Loop"}
            )
        if submitted_total == 0:
            recommendations.append(
                {
                    "title": "48 小时快速启动",
                    "anchorText": "4.1 两个快速启动清单（任选其一，从今天开始）",
                }
            )

        # 写入飞书汇总表的字段（只包含已有列）
        row = {
            "学生姓名": name,
            "关联学生": [s["roster_record_id"]] if s.get("roster_record_id") else [],
            "课程清单JSON": chunk_text_json(s["courses"]),
            "缺交总数": missing_total,
            "已提交总数": submitted_total,
            "缺交按课程JSON": chunk_text_json(missing_by_course),
            "课程进度JSON": chunk_text_json(course_progress),
            "缺交明细JSON": chunk_text_json(missing_items, max_len=50000),
            "近期提交JSON": chunk_text_json(recent),
            "推荐JSON": chunk_text_json(recommendations),
            "最后更新时间": now_ms,
        }
        # 花名册透传字段：暂存在 row 扩展区，不写飞书（列不存在会报错）
        # 等在飞书汇总表手动建好这些列后，把下面这段移入上面的 row dict 即可
        row["_extra"] = {
            "学年":      s.get("school_year", ""),
            "学期号":    s.get("semester_num", ""),
            "OSSLT状态": s.get("osslt", ""),
            "已获学分":  s.get("credits_earned", ""),
            "目标学分":  s.get("credits_target", ""),
            "公告":      s.get("notices_raw", ""),
            "近期提交周": week_label,
        }
        rows.append(row)
    print(
        ">>> 缺交匹配统计:",
        f"rows={missing_rows_total},",
        f"rows_with_link={missing_rows_with_link},",
        f"links_matched={missing_links_matched},",
        f"links_unmatched={missing_links_unmatched}",
    )
    return rows


def sync_summary_table(token, conf, summary_rows):
    app_token = conf["FEISHU_APP_TOKEN"]
    table_id = conf["FEISHU_SUMMARY_TABLE_ID"]
    existing = fetch_all_records(token, app_token, table_id)

    exist_map = {}
    for rec in existing:
        f = rec.get("fields", {})
        name = str(f.get("学生姓名", "")).strip()
        if name:
            exist_map[name] = rec.get("record_id")

    to_create = []
    to_update = []
    for row in summary_rows:
        name = row["学生姓名"]
        rid = exist_map.get(name)
        # _extra 仅用于 JSON 缓存，不写入飞书
        feishu_fields = {k: v for k, v in row.items() if k != "_extra"}
        if rid:
            to_update.append({"record_id": rid, "fields": feishu_fields})
        else:
            to_create.append(feishu_fields)

    batch_update(token, app_token, table_id, to_update)
    batch_create(token, app_token, table_id, to_create)
    print(
        f">>> 汇总同步完成：update={len(to_update)}, create={len(to_create)}, total={len(summary_rows)}"
    )


def write_json_cache(summary_rows, cache_dir):
    """把每个学生的汇总数据写成独立 JSON 文件，供 Node.js 直接读取（< 5ms）。
    文件命名规则与 server.js diskCacheFile() 保持一致：
      {tenant_key}__{student_name}.json
    env: CACHE_TENANT_KEY — 对应 server 的 tenantKey，默认 'default'
    """
    import re

    tenant_key = os.environ.get("CACHE_TENANT_KEY", "default").strip()

    def safe_name(s):
        return re.sub(r"[^\w\u4e00-\u9fff-]", "_", str(s))[:100]

    os.makedirs(cache_dir, exist_ok=True)
    written = 0
    for row in summary_rows:
        student_name = row.get("学生姓名", "")
        if not student_name:
            continue

        def load(key, fallback):
            v = row.get(key, "")
            if not v:
                return fallback
            try:
                return json.loads(v)
            except Exception:
                return fallback

        extra = row.get("_extra", {})
        payload = {
            "tenant": tenant_key,
            "studentName": student_name,
            "missingTotal": row.get("缺交总数", 0),
            "submittedTotal": row.get("已提交总数", 0),
            "courses": load("课程清单JSON", []),
            "courseProgress": load("课程进度JSON", []),
            "missingItems": load("缺交明细JSON", []),
            "missingByCourse": load("缺交按课程JSON", {}),
            "recentSubmissions": load("近期提交JSON", []),
            "recommendations": load("推荐JSON", []),
            "schoolYear":      extra.get("学年", ""),
            "semesterNum":     extra.get("学期号", ""),
            "osslt":           extra.get("OSSLT状态", ""),
            "creditsEarned":   extra.get("已获学分", None),
            "creditsTarget":   extra.get("目标学分", None),
            "noticesRaw":      extra.get("公告", ""),
            "recentWeekLabel": extra.get("近期提交周", ""),
            "_cachedAt": int(time.time() * 1000),
        }
        filename = f"{safe_name(tenant_key)}__{safe_name(student_name)}.json"
        with open(os.path.join(cache_dir, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        written += 1

    print(f">>> JSON 缓存写入完成: {written} 个文件 → {cache_dir}")


def main():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["FEISHU_APP_TOKEN"]

    roster = fetch_all_records(token, app_token, conf["FEISHU_ROSTER_TABLE_ID"])
    submissions = fetch_all_records(token, app_token, conf["FEISHU_TABLE_ID"])
    lib = fetch_all_records(token, app_token, conf["FEISHU_LIB_TABLE_ID"])
    missing = fetch_all_records(token, app_token, conf["FEISHU_MISSING_TABLE_ID"])
    print(
        f">>> 数据加载完成: roster={len(roster)}, submissions={len(submissions)}, lib={len(lib)}, missing={len(missing)}"
    )

    assignment_lookup, assignment_by_link = build_assignment_lookup(lib)
    summary_rows = build_summaries(roster, submissions, missing, assignment_lookup, assignment_by_link)
    sync_summary_table(token, conf, summary_rows)

    # 可选：同时写本地磁盘缓存（服务器上运行时设置 CACHE_DIR）
    cache_dir = os.environ.get("CACHE_DIR", "").strip()
    if cache_dir:
        write_json_cache(summary_rows, cache_dir)


if __name__ == "__main__":
    main()
