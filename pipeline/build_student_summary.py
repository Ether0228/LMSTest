import os
import json
import requests
import time
import re
from datetime import datetime, timedelta

# Gradebook 课程全名 → 课程代码映射（与 scrape_gradebook.py DEFAULT_COURSE_MAPPING 保持一致）
# 用于兼容飞书 Gradebook 表中存储的旧全名数据
_GRADEBOOK_COURSE_NAME_MAP = {
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
        "FEISHU_GRADEBOOK_TABLE_ID", #gradebook表
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
    # 防止单元格太长：逐条删除直到满足长度，避免在 JSON 中间截断
    if isinstance(obj, list):
        while len(text) > max_len and obj:
            obj = obj[:-1]
            text = json.dumps(obj, ensure_ascii=False)
        if len(text) <= max_len:
            return text
    # 非列表或无法缩减到限制：返回空 JSON
    return json.dumps([] if isinstance(obj, list) else {}, ensure_ascii=False)


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
    # rec_id -> {name, link, course, nature, semester}
    out = {}
    # clean_link -> {name, link, course, nature, semester}
    by_link = {}
    for rec in lib_records:
        rec_id = rec.get("record_id")
        f = rec.get("fields", {})
        item = {
            "name": str(f.get("作业名称", "")).strip(),
            "link": clean_schoology_url(normalize_link(f.get("作业链接"))),
            "course": str(f.get("所属课程", "")).strip(),
            "nature": str(f.get("作业性质", "")).strip(),
            "semester": str(f.get("学期", "")).strip(),
        }
        if rec_id:
            out[rec_id] = item
        link = item["link"]
        if link:
            by_link[link] = item
    return out, by_link


def build_nid_lookup(lib_records):
    """从作业库构建 NID → lib_item 映射（用于 gradebook 低分条目关联作业信息）。"""
    out = {}
    for rec in lib_records:
        f = rec.get("fields", {})
        link = clean_schoology_url(normalize_link(f.get("作业链接")))
        if not link:
            continue
        m = re.search(r'/(?:assignment|assessment|discussion)/(\d+)', link)
        if not m:
            continue
        nid = m.group(1)
        if nid not in out:
            out[nid] = {
                "name": str(f.get("作业名称", "")).strip(),
                "link": link,
                "course": str(f.get("所属课程", "")).strip(),
                "nature": str(f.get("作业性质", "")).strip(),
            }
    return out


def build_summaries(roster, submissions, missing, assignment_lookup, assignment_by_link,
                    gradebook_by_student=None, nid_to_lib=None, gp_info=None):
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
        sub_link = (
            (f.get("作业链接", {}) or {}).get("link", "")
            if isinstance(f.get("作业链接"), dict)
            else str(f.get("作业链接", ""))
        )
        students[name]["submitted"].append(
            {
                "assignmentName": f.get("作业名称", ""),
                "status": f.get("提交状态", ""),
                "submittedAt": f.get("提交时间", ""),
                "link": sub_link,
                "course": course_name,
                "nature": assignment.get("nature", ""),
            }
        )
        # 去重计数：同一作业多次提交只算 1 次（用作业链接作为唯一键，链接为空则用作业名）
        # 跳过"🚫 忽略"作业，与 expected_count 统计口径保持一致（否则会导致完成率 > 100%）
        if assignment.get("nature") != "🚫 忽略":
            sbc = students[name]["submitted_by_course"]
            dedup_key = sub_link or f.get("作业名称", "") or ""
            if course_name not in sbc:
                sbc[course_name] = set()
            sbc[course_name].add(dedup_key)

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
    week_last  = week_end - timedelta(days=1)   # 本周最后一天（周日），避免跨月时 day-1=0
    week_label = f"{week_start.month}/{week_start.day}-{week_last.month}/{week_last.day}"

    # 学期进度：从 grading_period.json 解析（由 scrape_gradebook.py 写入）
    semester_start_str = ""
    semester_end_str   = ""
    total_weeks        = None
    current_week       = None
    if gp_info and gp_info.get("start_date") and gp_info.get("end_date"):
        try:
            sem_start    = datetime.strptime(gp_info["start_date"], "%Y-%m-%d")
            sem_end      = datetime.strptime(gp_info["end_date"],   "%Y-%m-%d")
            today_dt     = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            total_days   = max(1, (sem_end - sem_start).days)
            total_weeks  = max(1, round(total_days / 7))
            elapsed_days = (today_dt - sem_start).days
            current_week = max(1, min(total_weeks, elapsed_days // 7 + 1))
            semester_start_str = gp_info["start_date"]
            semester_end_str   = gp_info["end_date"]
        except Exception as e:
            print(f"WARNING: 学期进度计算失败: {e}")

    # 预先解引用，避免在循环内部出现 NameError
    _gb_by_student = gradebook_by_student or {}
    _nid_to_lib = nid_to_lib or {}

    rows = []
    for name, s in students.items():
        missing_by_course = {}
        for item in s["missing"]:
            c = item["course"]
            missing_by_course[c] = missing_by_course.get(c, 0) + 1
        # courseProgress 只显示花名册里的课程，跨学期宽限期提交不额外增加课程卡
        all_courses = sorted(set(s["courses"]))

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
        # 按课程分组本学生的 gradebook 行，用于填充成绩数据
        _gb_rows_by_course = {}
        for gb_row in (_gb_by_student or {}).get(name, []):
            raw_name = str(gb_row.get("课程名", "")).strip()
            # 标准化内部空白（Schoology 课程名可能含多余空格，如 "Grade 12     Data Management"）
            normalized_name = re.sub(r'\s+', ' ', raw_name).lower()
            c_key = _GRADEBOOK_COURSE_NAME_MAP.get(normalized_name, raw_name)
            if c_key:
                _gb_rows_by_course.setdefault(c_key, []).append(gb_row)

        for c in all_courses:
            expected_count = int(s["expected_by_course"].get(c, 0))
            missing_count = int(missing_by_course.get(c, 0))
            submitted_from_expected = max(expected_count - missing_count, 0) if expected_count > 0 else 0
            sbc_val = s["submitted_by_course"].get(c)
            submitted_count = len(sbc_val) if sbc_val is not None else submitted_from_expected
            total = expected_count if expected_count > 0 else (submitted_count + missing_count)
            completion = round((submitted_count / total) * 100, 1) if total > 0 else 0.0

            # 从 gradebook 补充成绩字段
            gb_course_rows = _gb_rows_by_course.get(c, [])
            current_grade = None
            grade_updated_at = None
            aol_details = []
            if gb_course_rows:
                # 课程总分%：取第一个非空值（同一学生同一课程该值应一致）
                for r in gb_course_rows:
                    v = r.get("课程总分%")
                    if v is not None:
                        current_grade = round(float(v), 1)
                        grade_updated_at = now_ms
                        break
                # AoL 评分明细：分类名含 "aol" 或 "assessment of learning"
                for r in gb_course_rows:
                    cat = str(r.get("分类", "")).lower()
                    if "aol" not in cat and "assessment of learning" not in cat:
                        continue
                    score = r.get("得分")
                    max_score = r.get("满分")
                    if score is None or not max_score:
                        continue
                    aol_details.append({
                        "name":   str(r.get("作业名", "")).strip(),
                        "score":  round(float(score), 1),
                        "max":    round(float(max_score), 1),
                        "weight": r.get("分类权重%"),
                    })
                # 若无 AoL 分类条目，回退：展示所有有成绩的作业
                if not aol_details:
                    for r in gb_course_rows:
                        score = r.get("得分")
                        max_score = r.get("满分")
                        if score is None or not max_score:
                            continue
                        aol_details.append({
                            "name":     str(r.get("作业名", "")).strip(),
                            "score":    round(float(score), 1),
                            "max":      round(float(max_score), 1),
                            "category": str(r.get("分类", "")).strip(),
                            "weight":   r.get("分类权重%"),
                        })

            cp_entry = {
                "course":         c,
                "submittedCount": submitted_count,
                "missingCount":   missing_count,
                "completion":     completion,
                "aolSubmitted":   aol_submitted_by_course.get(c, 0),
                "aolMissing":     aol_missing_by_course.get(c, 0),
            }
            if current_grade is not None:
                cp_entry["current_grade"]    = current_grade
                cp_entry["grade_updated_at"] = grade_updated_at
            if aol_details:
                cp_entry["aol_details"] = aol_details
            course_progress.append(cp_entry)

        # DDL 日历：从 gradebook 提取未来截止日期
        upcoming_deadlines = []
        seen_ddl = set()
        for gb_row in _gb_by_student.get(name, []):
            due_ms = gb_row.get("截止日期")
            if not due_ms or not isinstance(due_ms, (int, float)):
                continue
            due_ms = int(due_ms)
            if due_ms <= now_ms:
                continue
            asgn_name = str(gb_row.get("作业名", "")).strip()
            if not asgn_name:
                continue
            raw_course = str(gb_row.get("课程名", "")).strip()
            normalized_course = re.sub(r'\s+', ' ', raw_course).lower()
            course_code = _GRADEBOOK_COURSE_NAME_MAP.get(normalized_course, raw_course)
            category = str(gb_row.get("分类", "")).strip()
            ddl_key = f"{due_ms}_{asgn_name}_{course_code}"
            if ddl_key in seen_ddl:
                continue
            seen_ddl.add(ddl_key)
            entry = {
                "date_ms":  due_ms,
                "course":   course_code,
                "name":     asgn_name,
                "category": category,
                "is_aol":   is_aol(category),
            }
            weight = gb_row.get("分类权重%")
            if weight is not None:
                entry["weight"] = weight
            upcoming_deadlines.append(entry)
        upcoming_deadlines.sort(key=lambda x: x["date_ms"])
        upcoming_deadlines = upcoming_deadlines[:30]

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

        # 关注列表：合并缺交 + 已交但低分（< 60%）
        attention_items = []
        # missing 部分
        for item in missing_items:
            is_hot = item.get("nature", "") == "🔥 极其重要"
            attention_items.append({
                "type": "missing",
                "course": item.get("course", ""),
                "assignmentName": item.get("assignmentName", ""),
                "assignmentLink": item.get("assignmentLink", ""),
                "nature": item.get("nature", ""),
                "_priority": 0 if is_hot else 1,
            })
        # low_score 部分
        for gb_row in _gb_by_student.get(name, []):
            if gb_row.get("已提交") != "✓":
                continue
            pct_raw = gb_row.get("得分率")
            try:
                pct = float(pct_raw) if pct_raw is not None else None
            except (TypeError, ValueError):
                pct = None
            if pct is None or pct >= 60:
                continue
            nid = str(gb_row.get("作业NID", "")).strip()
            lib_item = _nid_to_lib.get(nid, {})
            is_hot = lib_item.get("nature", "") == "🔥 极其重要"
            entry = {
                "type": "low_score",
                "course": str(gb_row.get("课程名", "")).strip() or lib_item.get("course", ""),
                "assignmentName": str(gb_row.get("作业名", "")).strip() or lib_item.get("name", ""),
                "assignmentLink": lib_item.get("link", ""),
                "nature": lib_item.get("nature", ""),
                "_priority": 2 if is_hot else 3,
            }
            if gb_row.get("得分") is not None:
                entry["score"] = float(gb_row["得分"])
            if gb_row.get("满分") is not None:
                entry["maxScore"] = float(gb_row["满分"])
            attention_items.append(entry)
        attention_items.sort(key=lambda x: x["_priority"])
        for _item in attention_items:
            _item.pop("_priority", None)

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
            "关注列表JSON": chunk_text_json(attention_items, max_len=50000),
            "DDL日历JSON":  json.dumps(upcoming_deadlines, ensure_ascii=False),
            "最后更新时间": now_ms,
            # 花名册透传字段：飞书汇总表建好对应列后自动生效
            "学年":      s.get("school_year", ""),
            "学期号":    s.get("semester_num", ""),
            "OSSLT状态": s.get("osslt", ""),
            "已获学分":  s.get("credits_earned", ""),
            "目标学分":  s.get("credits_target", ""),
            "公告":      s.get("notices_raw", ""),
        }
        # 学期时间数据仅用于 JSON 缓存，server 改从环境变量计算后不再需要
        row["_extra"] = {
            "近期提交周": week_label,
            "学期开始日期": semester_start_str,
            "学期结束日期": semester_end_str,
            "学期总周数":  total_weeks,
            "当前第几周":  current_week,
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

    # 拉取飞书表的实际列名，只写入已存在的列，避免 FieldNameNotFound
    fields_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    fields_resp = requests.get(fields_url, headers={"Authorization": f"Bearer {token}"}).json()
    known_fields = {item["field_name"] for item in fields_resp.get("data", {}).get("items", [])}
    if not known_fields:
        print("WARNING: 无法获取汇总表列信息，跳过写入")
        return
    skip_keys = {"_extra"} | (set() if not known_fields else set())  # _extra 始终跳过

    existing = fetch_all_records(token, app_token, table_id)

    exist_map = {}
    for rec in existing:
        f = rec.get("fields", {})
        name = str(f.get("学生姓名", "")).strip()
        if name:
            exist_map[name] = rec.get("record_id")

    to_create = []
    to_update = []
    skipped_fields = set()
    for row in summary_rows:
        name = row["学生姓名"]
        rid = exist_map.get(name)
        feishu_fields = {}
        for k, v in row.items():
            if k == "_extra":
                continue
            if k not in known_fields:
                skipped_fields.add(k)
                continue
            feishu_fields[k] = v
        if rid:
            to_update.append({"record_id": rid, "fields": feishu_fields})
        else:
            to_create.append(feishu_fields)

    if skipped_fields:
        print(f"INFO: 以下字段在汇总表中不存在，已跳过（飞书建列后自动生效）: {', '.join(sorted(skipped_fields))}")

    batch_update(token, app_token, table_id, to_update)
    batch_create(token, app_token, table_id, to_create)
    print(
        f">>> 汇总同步完成：update={len(to_update)}, create={len(to_create)}, total={len(summary_rows)}"
    )


def cleanup_ignored_from_missing_table(token, conf, assignment_lookup, missing_records):
    """删除飞书缺交表中关联到"🚫 忽略"作业的行。

    assignment_lookup: {record_id -> {nature, ...}} — 来自 build_assignment_lookup()
    missing_records:   fetch_all_records() 拉取的缺交表原始行列表
    """
    app_token = conf["FEISHU_APP_TOKEN"]
    table_id  = conf["FEISHU_MISSING_TABLE_ID"]

    ignored_ids = {aid for aid, a in assignment_lookup.items() if a.get("nature") == "🚫 忽略"}
    if not ignored_ids:
        print(">>> 无忽略作业，跳过缺交表清理")
        return

    to_delete = []
    for row in missing_records:
        linked = extract_linked_record_ids(row.get("fields", {}).get("关联作业"))
        if any(aid in ignored_ids for aid in linked):
            to_delete.append(row["record_id"])

    if not to_delete:
        print(f">>> 缺交表清理：没有需要删除的忽略作业行")
        return

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    deleted = 0
    for i in range(0, len(to_delete), 500):
        chunk = to_delete[i:i+500]
        resp = requests.post(url, headers=headers, json={"records": chunk}).json()
        if resp.get("code") == 0:
            deleted += len(chunk)
        else:
            print(f"  WARNING: 批量删除失败: {resp}")
    print(f">>> 缺交表清理完成：删除 {deleted} 行（忽略作业）")


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
            "attentionItems": load("关注列表JSON", []),
            "schoolYear":      row.get("学年", ""),
            "semesterNum":     row.get("学期号", ""),
            "osslt":           row.get("OSSLT状态", ""),
            "creditsEarned":   row.get("已获学分", None),
            "creditsTarget":   row.get("目标学分", None),
            "noticesRaw":      row.get("公告", ""),
            "recentWeekLabel": extra.get("近期提交周", ""),
            "semesterStart":   extra.get("学期开始日期", ""),
            "semesterEnd":     extra.get("学期结束日期", ""),
            "totalWeeks":      extra.get("学期总周数",   None),
            "currentWeek":     extra.get("当前第几周",   None),
            "_cachedAt": int(time.time() * 1000),
        }
        filename = f"{safe_name(tenant_key)}__{safe_name(student_name)}.json"
        with open(os.path.join(cache_dir, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        written += 1

    print(f">>> JSON 缓存写入完成: {written} 个文件 → {cache_dir}")


def write_pg_cache(summary_rows, database_url, tenant_key=None):
    """把每个学生的汇总数据写入 PostgreSQL student_summary 表（作为读取缓存层）。
    数据结构与 write_json_cache() 完全一致，server.js 可零改动读取。
    env: CACHE_TENANT_KEY — 对应 server 的 tenantKey，默认 'default'
    """
    import re
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("WARNING: psycopg2 未安装，跳过 PostgreSQL 写入。请 pip install psycopg2-binary")
        return

    if not database_url:
        print("INFO: DATABASE_URL 未设置，跳过 PostgreSQL 写入")
        return

    if tenant_key is None:
        tenant_key = os.environ.get("CACHE_TENANT_KEY", "default").strip()

    def load(row, key, fallback):
        v = row.get(key, "")
        if not v:
            return fallback
        try:
            return json.loads(v)
        except Exception:
            return fallback

    rows_to_insert = []
    for row in summary_rows:
        student_name = row.get("学生姓名", "")
        if not student_name:
            continue
        extra = row.get("_extra", {})
        payload = {
            "tenant":          tenant_key,
            "studentName":     student_name,
            "missingTotal":    row.get("缺交总数", 0),
            "submittedTotal":  row.get("已提交总数", 0),
            "courses":         load(row, "课程清单JSON", []),
            "courseProgress":  load(row, "课程进度JSON", []),
            "missingItems":    load(row, "缺交明细JSON", []),
            "missingByCourse": load(row, "缺交按课程JSON", {}),
            "recentSubmissions": load(row, "近期提交JSON", []),
            "recommendations": load(row, "推荐JSON", []),
            "attentionItems":  load(row, "关注列表JSON", []),
            "upcomingDeadlines": load(row, "DDL日历JSON", []),
            "schoolYear":      row.get("学年", ""),
            "semesterNum":     row.get("学期号", ""),
            "osslt":           row.get("OSSLT状态", ""),
            "creditsEarned":   row.get("已获学分", None),
            "creditsTarget":   row.get("目标学分", None),
            "noticesRaw":      row.get("公告", ""),
            "recentWeekLabel": extra.get("近期提交周", ""),
            "semesterStart":   extra.get("学期开始日期", ""),
            "semesterEnd":     extra.get("学期结束日期", ""),
            "totalWeeks":      extra.get("学期总周数", None),
            "currentWeek":     extra.get("当前第几周", None),
            "_cachedAt":       int(time.time() * 1000),
        }
        rows_to_insert.append((tenant_key, student_name, psycopg2.extras.Json(payload)))

    if not rows_to_insert:
        print("INFO: 无学生数据，跳过 PostgreSQL 写入")
        return

    try:
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS student_summary (
              tenant       TEXT NOT NULL,
              student_name TEXT NOT NULL,
              data         JSONB NOT NULL,
              updated_at   TIMESTAMPTZ DEFAULT NOW(),
              PRIMARY KEY (tenant, student_name)
            )""")
        psycopg2.extras.execute_values(cur,
            """INSERT INTO student_summary(tenant, student_name, data) VALUES %s
               ON CONFLICT(tenant, student_name)
               DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()""",
            rows_to_insert)
        conn.commit()
        cur.close()
        conn.close()
        print(f"  ✓ PostgreSQL 写入 {len(rows_to_insert)} 条 → tenant={tenant_key}")
    except Exception as e:
        print(f"WARNING: PostgreSQL 写入失败: {e}")


def main():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["FEISHU_APP_TOKEN"]

    roster = fetch_all_records(token, app_token, conf["FEISHU_ROSTER_TABLE_ID"])
    submissions = fetch_all_records(token, app_token, conf["FEISHU_TABLE_ID"])
    lib = fetch_all_records(token, app_token, conf["FEISHU_LIB_TABLE_ID"])
    missing = fetch_all_records(token, app_token, conf["FEISHU_MISSING_TABLE_ID"])

    # 可选：gradebook 表（用于计算低分关注列表）
    gradebook_table_id = os.environ.get("FEISHU_GRADEBOOK_TABLE_ID", "").strip()
    gradebook_rows = []
    if gradebook_table_id:
        gradebook_records = fetch_all_records(token, app_token, gradebook_table_id)
        gradebook_rows = [r.get("fields", {}) for r in gradebook_records]
        print(f">>> gradebook={len(gradebook_rows)} 条")
    else:
        print("WARNING: FEISHU_GRADEBOOK_TABLE_ID 未设置 — 成绩数据和低分关注列表将为空。"
              "如需成绩功能请在 GitHub Secrets 中配置此变量。")

    print(
        f">>> 数据加载完成: roster={len(roster)}, submissions={len(submissions)}, lib={len(lib)}, missing={len(missing)}"
    )

    # 学期过滤：只有 ACTIVE_SEMESTERS 里的学期（或无标签的旧数据）参与缺交考核
    active_semesters_raw = os.environ.get("ACTIVE_SEMESTERS", "").strip()
    active_semesters = {s.strip() for s in active_semesters_raw.split(",") if s.strip()} if active_semesters_raw else set()
    if active_semesters:
        lib_before = len(lib)
        lib = [
            rec for rec in lib
            if not str(rec.get("fields", {}).get("学期", "")).strip()
            or str(rec.get("fields", {}).get("学期", "")).strip() in active_semesters
        ]
        print(f">>> 学期过滤 ({', '.join(sorted(active_semesters))}): {lib_before} → {len(lib)} 条作业参与考核")
    else:
        print("INFO: ACTIVE_SEMESTERS 未设置，所有非忽略作业计入考核（向后兼容模式）")

    assignment_lookup, assignment_by_link = build_assignment_lookup(lib)
    nid_to_lib = build_nid_lookup(lib)
    gradebook_by_student = {}
    for gb_row in gradebook_rows:
        name = str(gb_row.get("学生姓名", "")).strip()
        if not name:
            continue
        gradebook_by_student.setdefault(name, []).append(gb_row)

    # 读取学期元数据：
    # 优先读本地文件（scrape_gradebook.py 在同一 job 内运行时写入）
    # 其次读 SCHOOLOGY_GRADING_PERIOD 环境变量（main_pipeline 跨 job 时由 Secret 提供）
    gp_info = {}
    gp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grading_period.json")
    if os.path.exists(gp_path):
        try:
            with open(gp_path, "r", encoding="utf-8") as f:
                gp_info = json.load(f)
            print(f">>> 学期参数 [本地文件]: {gp_info.get('session', '')} {gp_info.get('start_date', '')} → {gp_info.get('end_date', '')}")
        except Exception as e:
            print(f"WARNING: 读取 grading_period.json 失败: {e}")
    else:
        gp_raw = os.environ.get("SCHOOLOGY_GRADING_PERIOD", "").strip()
        if gp_raw:
            try:
                gp_info = json.loads(gp_raw)
                print(f">>> 学期参数 [环境变量]: {gp_info.get('session', '')} {gp_info.get('start_date', '')} → {gp_info.get('end_date', '')}")
            except Exception as e:
                print(f"WARNING: 解析 SCHOOLOGY_GRADING_PERIOD 失败: {e}")
        else:
            print("INFO: 未找到学期参数（grading_period.json 或 SCHOOLOGY_GRADING_PERIOD），学期进度条将不显示。"
                  "切换学期后请在 GitHub Secrets 中设置 SCHOOLOGY_GRADING_PERIOD。")

    summary_rows = build_summaries(
        roster, submissions, missing, assignment_lookup, assignment_by_link,
        gradebook_by_student, nid_to_lib, gp_info=gp_info,
    )

    # 清理飞书缺交表中"🚫 忽略"作业的行
    cleanup_ignored_from_missing_table(token, conf, assignment_lookup, missing)

    # 可选：同时写本地磁盘缓存（服务器上运行时设置 CACHE_DIR）
    cache_dir = os.environ.get("CACHE_DIR", "").strip()
    if cache_dir:
        write_json_cache(summary_rows, cache_dir)

    # 可选：写 PostgreSQL 缓存（设置 DATABASE_URL 后启用，作为最快读取路径）
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        tenant_key = os.environ.get("CACHE_TENANT_KEY", "default").strip()
        write_pg_cache(summary_rows, database_url, tenant_key)


if __name__ == "__main__":
    main()
