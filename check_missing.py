import os
import json
import requests
from datetime import datetime, timedelta

def get_env_config():
    return {
        "app_id": os.environ.get("FEISHU_APP_ID").strip(),
        "app_secret": os.environ.get("FEISHU_APP_SECRET").strip(),
        "app_token": os.environ.get("FEISHU_APP_TOKEN").strip(),
        "table_id": os.environ.get("FEISHU_TABLE_ID").strip(),        # 提交记录表
        "roster_tid": os.environ.get("FEISHU_ROSTER_TABLE_ID").strip(), # 花名册表
        "lib_tid": os.environ.get("FEISHU_LIB_TABLE_ID").strip(),       # 作业库表
        "missing_tid": os.environ.get("FEISHU_MISSING_TABLE_ID").strip() # 缺交记录表
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

def start_missing_check():
    conf = get_env_config()
    token = get_feishu_token(conf)
    app_token = conf["app_token"]

    print(">>> 正在拉取基础数据...")
    roster = fetch_all_records(token, app_token, conf["roster_tid"])
    lib = fetch_all_records(token, app_token, conf["lib_tid"])
    submissions = fetch_all_records(token, app_token, conf["table_id"])

    # 1. 整理已提交的 ID 集合 (学生ID + 作业ID)
    # 集合内容示例: {"recStudentA_recAssignmentB"}
    submitted_set = set()
    for sub in submissions:
        fields = sub.get("fields", {})
        s_ids = fields.get("关联学生", [])
        a_ids = fields.get("关联作业", [])
        if s_ids and a_ids:
            submitted_set.add(f"{s_ids[0]}_{a_ids[0]}")

    # 2. 计算应交全集并对比
    missing_to_write = []
    update_time = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")

    for a_rec in lib:
        a_fields = a_rec.get("fields", {})
        # 仅统计必交作业
        if a_fields.get("统计状态") != "✅ 必交": continue
        
        a_id = a_rec.get("record_id")
        a_course = a_fields.get("所属课程")
        a_name = a_fields.get("作业名称")
        
        if not a_course: continue

        for s_rec in roster:
            s_fields = s_rec.get("fields", {})
            s_id = s_rec.get("record_id")
            s_courses = s_fields.get("所属课程", []) # 多选字段是列表
            
            # 判断学生是否选了这门课
            if a_course in s_courses:
                key = f"{s_id}_{a_id}"
                if key not in submitted_set:
                    # 发现缺交
                    missing_to_write.append({
                        "fields": {
                            "关联学生": [s_id],
                            "关联作业": [a_id],
                            "所属课程": a_course,
                            "更新时间": update_time
                        }
                    })

    # 3. 刷新缺交记录表 (全删全加)
    print(f">>> 发现 {len(missing_to_write)} 条缺交记录。正在更新...")
    
    # 获取旧记录并删除
    old_missing = fetch_all_records(token, app_token, conf["missing_tid"])
    old_ids = [r["record_id"] for r in old_missing]
    
    delete_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['missing_tid']}/records/batch_delete"
    for i in range(0, len(old_ids), 100):
        requests.post(delete_url, json={"records": old_ids[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    # 写入新记录
    create_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{conf['missing_tid']}/records/batch_create"
    for i in range(0, len(missing_to_write), 100):
        requests.post(create_url, json={"records": missing_to_write[i:i+100]}, headers={"Authorization": f"Bearer {token}"})

    print(">>> 缺交记录表更新完毕！")

if __name__ == "__main__":
    start_missing_check()
