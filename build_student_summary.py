import os
import json
import requests
import time


def get_env_config():
    keys = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN",
        "FEISHU_TABLE_ID",  # 提交记录表
        "FEISHU_ROSTER_TABLE_ID",  # 学生花名册
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


def build_summaries(roster, submissions, missing):
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
        }

    # 2) 提交记录聚合（按“学生姓名”文本）
    for s in submissions:
        f = s.get("fields", {})
        name = str(f.get("学生姓名", "")).strip()
        if not name or name not in students:
            continue
        students[name]["submitted"].append(
            {
                "assignmentName": f.get("作业名称", ""),
                "status": f.get("提交状态", ""),
                "submittedAt": f.get("提交时间", ""),
                "link": (f.get("作业链接", {}) or {}).get("link", "")
                if isinstance(f.get("作业链接"), dict)
                else str(f.get("作业链接", "")),
            }
        )

    # 3) 缺交记录聚合（按“关联学生” record_id）
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
        if linked:
            missing_rows_with_link += 1
        for rid in linked:
            name = roster_id_to_name.get(rid)
            if not name:
                missing_links_unmatched += 1
                continue
            missing_links_matched += 1
            students[name]["missing"].append(
                {
                    "course": str(f.get("所属课程", "")).strip() or "未分类",
                    "status": f.get("处理状态", ""),
                }
            )

    # 4) 汇总字段
    now_ms = int(time.time() * 1000)
    rows = []
    for name, s in students.items():
        missing_by_course = {}
        for item in s["missing"]:
            c = item["course"]
            missing_by_course[c] = missing_by_course.get(c, 0) + 1

        submitted_sorted = sorted(
            s["submitted"], key=lambda x: str(x.get("submittedAt", "")), reverse=True
        )
        recent = submitted_sorted[:20]
        missing_total = len(s["missing"])
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

        row = {
            "学生姓名": name,
            "关联学生": [s["roster_record_id"]] if s.get("roster_record_id") else [],
            "课程清单JSON": chunk_text_json(s["courses"]),
            "缺交总数": missing_total,
            "已提交总数": submitted_total,
            "缺交按课程JSON": chunk_text_json(missing_by_course),
            "近期提交JSON": chunk_text_json(recent),
            "推荐JSON": chunk_text_json(recommendations),
            "最后更新时间": now_ms,
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
        if rid:
            to_update.append({"record_id": rid, "fields": row})
        else:
            to_create.append(row)

    batch_update(token, app_token, table_id, to_update)
    batch_create(token, app_token, table_id, to_create)
    print(
        f">>> 汇总同步完成：update={len(to_update)}, create={len(to_create)}, total={len(summary_rows)}"
    )


def main():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["FEISHU_APP_TOKEN"]

    roster = fetch_all_records(token, app_token, conf["FEISHU_ROSTER_TABLE_ID"])
    submissions = fetch_all_records(token, app_token, conf["FEISHU_TABLE_ID"])
    missing = fetch_all_records(token, app_token, conf["FEISHU_MISSING_TABLE_ID"])
    print(
        f">>> 数据加载完成: roster={len(roster)}, submissions={len(submissions)}, missing={len(missing)}"
    )

    summary_rows = build_summaries(roster, submissions, missing)
    sync_summary_table(token, conf, summary_rows)


if __name__ == "__main__":
    main()
