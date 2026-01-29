import os
import json
import requests
import re
import hashlib
import time
from datetime import datetime, timedelta

# ================= 配置与工具函数 =================
def get_env_config():
    keys = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN", 
            "FEISHU_TABLE_ID", "FEISHU_ROSTER_TABLE_ID", 
            "FEISHU_LIB_TABLE_ID", "FEISHU_MISSING_TABLE_ID"]
    conf = {k: os.environ.get(k, "").strip() for k in keys}
    if not all(conf.values()):
        raise ValueError("GitHub Secrets 配置不完整，请检查 Table ID 和 API 密钥")
    return conf

def get_feishu_token(conf):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": conf["FEISHU_APP_ID"], "app_secret": conf["FEISHU_APP_SECRET"]})
    return resp.json().get("tenant_access_token")

def clean_url(url):
    """确保链接格式统一，只保留到ID部分"""
    if not url: return ""
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', str(url))
    return match.group(1) if match else str(url).strip()

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

# ================= 核心同步逻辑 =================
def start_missing_sync():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["FEISHU_APP_TOKEN"]

    print(">>> 正在拉取数据进行 [作业链接] 匹配核验...")
    roster = fetch_all_records(token, app_token, conf["FEISHU_ROSTER_TABLE_ID"])
    lib = fetch_all_records(token, app_token, conf["FEISHU_LIB_TABLE_ID"])
    submissions = fetch_all_records(token, app_token, conf["FEISHU_TABLE_ID"])
    current_missing_table = fetch_all_records(token, app_token, conf["FEISHU_MISSING_TABLE_ID"])

    # 【关键修正】使用 Unix 绝对时间戳，解决时区显示问题
    absolute_now_ms = int(time.time() * 1000)

    # 1. 建立【已提交】索引 (基于 姓名 + 链接)
    submitted_keys = set()
    for sub in submissions:
        f = sub.get("fields", {})
        s_name = f.get("学生姓名", "")
        # 处理链接列
        link_data = f.get("作业链接", {})
        link_url = link_data.get("link", "") if isinstance(link_data, dict) else str(link_data)
        
        if s_name and link_url:
            key = f"{s_name}_{clean_url(link_url)}"
            submitted_keys.add(key)
    
    print(f">>> 识别到已提交有效组合: {len(submitted_keys)} 条")

    # 2. 建立【缺交表】现有数据映射
    table_existing_map = {} 
    manual_confirmed_keys = set() 
    
    for rec in current_missing_table:
        f = rec.get("fields", {})
        u_id = f.get("唯一标识")
        if u_id:
            table_existing_map[u_id] = rec.get("record_id")
            if f.get("手动确认提交") == True:
                manual_confirmed_keys.add(u_id)

    # 3. 计算【应交】全集并对比
    logic_missing_data = {}
    
    for a_rec in lib:
        a_f = a_rec.get("fields", {})
        if a_f.get("统计状态") != "✅ 必交": continue
        
        a_id = a_rec.get("record_id")
        a_url = clean_url(a_f.get("作业链接", ""))
        a_course = a_f.get("所属课程")
        
        if not a_url or not a_course: continue

        for s_rec in roster:
            s_f = s_rec.get("fields", {})
            s_name = s_f.get("学生姓名")
            s_id = s_rec.get("record_id")
            s_courses = s_f.get("所属课程", [])
            if not isinstance(s_courses, list): s_courses = [s_courses]
            
            # 判断逻辑：学生选了这门课
            if a_course in s_courses:
                match_key = f"{s_name}_{a_url}"
                unique_id = hashlib.md5(match_key.encode('utf-8')).hexdigest()
                
                # 如果 没交 且 老师没手动点确认，就加入缺交字典
                if match_key not in submitted_keys and unique_id not in manual_confirmed_keys:
                    logic_missing_data[unique_id] = {
                        "s_id": s_id,
                        "a_id": a_id,
                        "course": a_course
                    }

    # 4. 同步决策
    new_keys = set(logic_missing_data.keys())
    existing_keys = set(table_existing_map.keys())

    to_add = new_keys - existing_keys
    to_delete = []
    # 逻辑销账：在表里有，但逻辑上不缺了，且老师没手动确认过，才删除
    for k in (existing_keys - new_keys):
        if k not in manual_confirmed_keys:
            to_delete.append(table_existing_map[k])
            
    to_update_time = (new_keys & existing_keys) # 持续缺交的

    print(f">>> [结果] 新增: {len(to_add)} | 销账: {len(to_delete)} | 持续: {len(to_update_time)} | 手动保留: {len(manual_confirmed_keys)}")

    # === 执行 API 操作 ===
    # A. 删除
    if to_delete:
        del_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_delete"
        for i in range(0, len(to_delete), 100):
            requests.post(del_url, json={"records": to_delete[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # B. 更新时间
    if to_update_time:
        upd_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_update"
        upd_rows = [{"record_id": table_existing_map[k], "fields": {"最后核验时间": absolute_now_ms}} for k in to_update_time]
        for i in range(0, len(upd_rows), 100):
            requests.post(upd_url, json={"records": upd_rows[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # C. 新增
    if to_add:
        add_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['FEISHU_MISSING_TABLE_ID']}/records/batch_create"
        add_payload = []
        for k in to_add:
            info = logic_missing_data[k]
            add_payload.append({"fields": {
                "唯一标识": k,
                "关联学生": [info["s_id"]],
                "关联作业": [info["a_id"]],
                "所属课程": info["course"],
                "发现日期": absolute_now_ms,
                "最后核验时间": absolute_now_ms,
                "处理状态": "待处理"
            }})
        for i in range(0, len(add_payload), 100):
            batch = add_payload[i:i+100]
            resp = requests.post(add_url, json={"records": batch}, headers={"Authorization": f"Bearer {token}"}).json()
            if resp.get("code") != 0:
                print(f"!!! 写入失败: {resp.get('msg')}")

    print(">>> 缺交核验全流程同步完毕。")

if __name__ == "__main__":
    start_missing_sync()
