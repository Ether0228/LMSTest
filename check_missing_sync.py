import os
import json
import requests
from datetime import datetime, timedelta

def get_env_config():
    # 强制检查所有环境变量
    keys = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", 
            "FEISHU_TABLE_ID", "FEISHU_ROSTER_TABLE_ID", 
            "FEISHU_LIB_TABLE_ID", "FEISHU_MISSING_TABLE_ID"]
    conf = {}
    for k in keys:
        val = os.environ.get(k, "").strip()
        if not val:
            raise ValueError(f"缺少环境变量: {k}")
        conf[k] = val
    return conf

def get_feishu_token(conf):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": conf["FEISHU_APP_ID"], "app_secret": conf["FEISHU_APP_SECRET"]})
    return resp.json().get("tenant_access_token")

def fetch_all_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 1000}
        if page_token: params["page_token"] = page_token
        try:
            resp = requests.get(url, headers=headers, params=params).json()
            if resp.get("code") != 0: break
            data = resp.get("data", {})
            records.extend(data.get("items", []))
            if not data.get("has_more"): break
            page_token = data.get("page_token")
        except: break
    return records

def start_missing_sync():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["FEISHU_APP_TOKEN"]

    print(">>> 正在读取基础数据...")
    roster = fetch_all_records(token, app_token, conf["FEISHU_ROSTER_TABLE_ID"])
    lib = fetch_all_records(token, app_token, conf["FEISHU_LIB_TABLE_ID"])
    submissions = fetch_all_records(token, app_token, conf["FEISHU_TABLE_ID"])
    current_missing_table = fetch_all_records(token, app_token, conf["FEISHU_MISSING_TABLE_ID"])

    beijing_now_ms = int((datetime.utcnow() + timedelta(hours=8)).timestamp() * 1000)

    # 1. 已提交集合
    submitted_set = set()
    for sub in submissions:
        f = sub.get("fields", {})
        s_ids, a_ids = f.get("关联学生", []), f.get("关联作业", [])
        if s_ids and a_ids: submitted_set.add(f"{s_ids[0]}_{a_ids[0]}")

    # 2. 提取人工确认和现有映射
    manual_confirmed_set = set()
    table_existing_map = {}
    for rec in current_missing_table:
        f = rec.get("fields", {})
        u_id = f.get("唯一标识")
        if u_id:
            table_existing_map[u_id] = rec.get("record_id")
            if f.get("手动确认提交") == True:
                manual_confirmed_set.add(u_id)

    # 3. 计算逻辑应交
    calculated_missing_map = {}
    for a_rec in lib:
        a_f = a_rec.get("fields", {})
        if a_f.get("统计状态") != "✅ 必交": continue
        a_id, a_course = a_rec.get("record_id"), a_f.get("所属课程")
        if not a_course: continue
        
        for s_rec in roster:
            s_f = s_rec.get("fields", {})
            s_id, s_courses = s_rec.get("record_id"), s_f.get("所属课程", [])
            # 兼容多选和单选
            if not isinstance(s_courses, list): s_courses = [s_courses]
            
            if a_course in s_courses:
                key = f"{s_id}_{a_id}"
                if key not in submitted_set and key not in manual_confirmed_set:
                    calculated_missing_map[key] = {"s_id": s_id, "a_id": a_id, "course": a_course}

    # 4. 决策
    new_keys = set(calculated_missing_map.keys())
    existing_keys = set(table_existing_map.keys())

    to_add = new_keys - existing_keys
    to_delete = []
    for k in (existing_keys - new_keys):
        if k not in manual_confirmed_set: to_delete.append(table_existing_map[k])
    to_verify = (new_keys & existing_keys) - manual_confirmed_set

    print(f">>> [核验结果] 新增: {len(to_add)} | 销账: {len(to_delete)} | 持续: {len(to_verify)} | 手动保留: {len(manual_confirmed_set)}")

    # === 执行 API 操作 (核心修复部分) ===
    
    # A. 删除 (销账)
    if to_delete:
        print(f">>> 正在执行 {len(to_delete)} 条销账...")
        del_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_delete"
        for i in range(0, len(to_delete), 100):
            requests.post(del_url, json={"records": to_delete[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # B. 更新 (最后核验时间)
    if to_verify:
        print(f">>> 正在更新 {len(to_verify)} 条存量记录时间...")
        upd_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_update"
        upd_rows = [{"record_id": table_existing_map[k], "fields": {"最后核验时间": beijing_now_ms}} for k in to_verify]
        for i in range(0, len(upd_rows), 100):
            requests.post(upd_url, json={"records": upd_rows[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # C. 新增 (写入新缺交)
    if to_add:
        print(f">>> 正在写入 {len(to_add)} 条新缺交记录...")
        add_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_create"
        add_rows = []
        for k in to_add:
            info = calculated_missing_map[k]
            add_rows.append({"fields": {
                "唯一标识": k,
                "关联学生": [info["s_id"]],
                "关联作业": [info["a_id"]],
                "所属课程": info["course"],
                "发现日期": beijing_now_ms,
                "最后核验时间": beijing_now_ms,
                "处理状态": "待处理"
            }})
        
        for i in range(0, len(add_rows), 100):
            batch = add_rows[i:i+100]
            resp = requests.post(add_url, json={"records": batch}, headers={"Authorization": f"Bearer {token}"}).json()
            if resp.get("code") != 0:
                print(f"!!! 批量写入失败! 错误信息: {resp.get('msg')}")
                # 如果是因为缺少字段，这里会报错

    print(">>> 全流程同步完毕。")

if __name__ == "__main__":
    start_missing_sync()
