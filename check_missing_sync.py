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

    print(">>> 正在进行深度核验 (包含人工销账检查)...")
    roster = fetch_all_records(token, app_token, conf["roster_tid"])
    lib = fetch_all_records(token, app_token, conf["lib_tid"])
    submissions = fetch_all_records(token, app_token, conf["table_id"])
    current_missing_table = fetch_all_records(token, app_token, conf["missing_tid"])

    beijing_now_ms = int((datetime.utcnow() + timedelta(hours=8)).timestamp() * 1000)

    # 1. 提取【自动化】已提交集合 (来自 Submissions 表)
    submitted_set = set()
    for sub in submissions:
        f = sub.get("fields", {})
        s_ids, a_ids = f.get("关联学生", []), f.get("关联作业", [])
        if s_ids and a_ids: 
            submitted_set.add(f"{s_ids[0]}_{a_ids[0]}")

    # 2. 提取【人工确认】已提交集合 (来自 缺交记录表)
    manual_confirmed_set = set()
    table_existing_map = {} # { unique_id: record_id }
    manual_confirmed_records = set() # 记录哪些 record_id 是老师手动勾选的

    for rec in current_missing_table:
        f = rec.get("fields", {})
        u_id = f.get("唯一标识")
        if not u_id: continue
        
        table_existing_map[u_id] = rec.get("record_id")
        
        # 【关键】检查“手动确认提交”复选框是否被勾选
        # 或者是检查“处理状态”是否为“手动确认”
        if f.get("手动确认提交") == True:
            manual_confirmed_set.add(u_id)
            manual_confirmed_records.add(u_id)

    # 3. 计算应交全集
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
                
                # 【逻辑修正】
                # 只有 自动化没抓到 且 老师没手动确认 的，才算真正的“缺交”
                if key not in submitted_set and key not in manual_confirmed_set:
                    calculated_missing_map[key] = {"s_id": s_id, "a_id": a_id, "course": a_course}

    # 4. 同步决策
    new_keys = set(calculated_missing_map.keys())
    existing_keys = set(table_existing_map.keys())

    # A. 真正的新缺交
    to_add = new_keys - existing_keys
    
    # B. 需要销账的
    # 逻辑：在表里有，但 (自动化抓到了新提交) 的记录
    # 注意：千万不能删除老师已经“手动确认”的记录！
    to_delete = []
    for k in (existing_keys - new_keys):
        # 只有当这条记录不是“手动确认”的，才由机器人自动删除
        if k not in manual_confirmed_set:
            to_delete.append(table_existing_map[k])

    # C. 需要持续核验的
    # 逻辑：逻辑上缺交 且 表里已有 且 老师还没确认
    to_verify = (new_keys & existing_keys) - manual_confirmed_set

    print(f">>> [核验结果] 新增缺交: {len(to_add)} | 自动销账: {len(to_delete)} | 维持缺交: {len(to_verify)} | 手动保留: {len(manual_confirmed_set)}")

if __name__ == "__main__":
    start_missing_sync()
