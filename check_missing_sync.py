import os
import json
import requests
import hashlib
from datetime import datetime, timedelta

def get_env_config():
    return {
        "app_id": os.environ.get("FEISHU_APP_ID").strip(),
        "app_secret": os.environ.get("FEISHU_APP_SECRET").strip(),
        "app_token": os.environ.get("FEISHU_APP_TOKEN").strip(),
        "table_id": os.environ.get("FEISHU_TABLE_ID").strip(),
        "roster_tid": os.environ.get("FEISHU_ROSTER_TABLE_ID").strip(),
        "lib_tid": os.environ.get("FEISHU_LIB_TABLE_ID").strip(),
        "missing_tid": os.environ.get("FEISHU_MISSING_TABLE_ID").strip()
    }

def get_feishu_token(conf):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": conf["app_id"], "app_secret": conf["app_secret"]})
    return resp.json().get("tenant_access_token")

def fetch_all_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 1000}
        if page_token: params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0: break
        items = resp.get("data", {}).get("items", [])
        records.extend(items)
        if not resp.get("data", {}).get("has_more"): break
        page_token = resp.get("data", {}).get("page_token")
    return records

def start_missing_sync():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["app_token"]

    print(">>> 正在进行深度核验...")
    roster = fetch_all_records(token, app_token, conf["roster_tid"])
    lib = fetch_all_records(token, app_token, conf["lib_tid"])
    submissions = fetch_all_records(token, app_token, conf["table_id"])
    current_missing_table = fetch_all_records(token, app_token, conf["missing_tid"])

    # 北京时间现在
    beijing_now_ms = int((datetime.utcnow() + timedelta(hours=8)).timestamp() * 1000)

    # 1. 提取已提交集合
    submitted_set = set()
    for sub in submissions:
        f = sub.get("fields", {})
        s_ids, a_ids = f.get("关联学生", []), f.get("关联作业", [])
        if s_ids and a_ids: submitted_set.add(f"{s_ids[0]}_{a_ids[0]}")

    # 2. 计算应交全集
    calculated_missing_map = {}
    for a_rec in lib:
        a_f = a_rec.get("fields", {})
        if a_f.get("统计状态") != "✅ 必交": continue
        a_id, a_course = a_rec.get("record_id"), a_f.get("所属课程")
        if not a_course: continue
        for s_rec in roster:
            s_f = s_rec.get("fields", {})
            s_id, s_courses = s_rec.get("record_id"), s_f.get("所属课程", [])
            if a_course in s_courses:
                key = f"{s_id}_{a_id}"
                if key not in submitted_set:
                    calculated_missing_map[key] = {"s_id": s_id, "a_id": a_id, "course": a_course}

    # 3. 提取现有缺交表数据
    table_existing_map = {} # { unique_id: record_id }
    for rec in current_missing_table:
        u_id = rec.get("fields", {}).get("唯一标识")
        if u_id: table_existing_map[u_id] = rec.get("record_id")

    # 4. 同步决策
    new_keys = set(calculated_missing_map.keys())
    existing_keys = set(table_existing_map.keys())

    to_add = new_keys - existing_keys
    to_delete = [table_existing_map[k] for k in (existing_keys - new_keys)]
    to_verify = new_keys & existing_keys # 依然缺交的存量数据

    print(f">>> [核验结果] 新缺交: {len(to_add)} | 补交销账: {len(to_delete)} | 持续缺交: {len(to_verify)}")

    # A. 删除已补交的记录
    if to_delete:
        del_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['missing_tid']}/records/batch_delete"
        for i in range(0, len(to_delete), 100):
            requests.post(del_url, json={"records": to_delete[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # B. 新增缺交记录
    if to_add:
        add_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['missing_tid']}/records/batch_create"
        rows = []
        for k in to_add:
            info = calculated_missing_map[k]
            rows.append({"fields": {
                "唯一标识": k,
                "关联学生": [info["s_id"]],
                "关联作业": [info["a_id"]],
                "所属课程": info["course"],
                "发现日期": beijing_now_ms,
                "最后核验时间": beijing_now_ms,
                "处理状态": "待处理"
            }})
        for i in range(0, len(rows), 100):
            requests.post(add_url, json={"records": rows[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # C. 【关键】更新存量记录的“核验时间”
    if to_verify:
        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['missing_tid']}/records/batch_update"
        update_rows = []
        for k in to_verify:
            update_rows.append({
                "record_id": table_existing_map[k],
                "fields": {
                    "最后核验时间": beijing_now_ms  # 仅更新核验时间，保留备注和状态
                }
            })
        for i in range(0, len(update_rows), 100):
            requests.post(update_url, json={"records": update_rows[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    print(">>> 核验流程结束。")

if __name__ == "__main__":
    start_missing_sync()
