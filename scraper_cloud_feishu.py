import os
import json
import time
import requests
import re
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区域 =================
LOGIN_URL = "https://queenscanada.schoology.com"
NOTIFICATION_URL = "https://queenscanada.schoology.com/home/notifications"
# ===========================================

def get_env_config():
    # 获取飞书配置
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    app_token = os.environ.get("FEISHU_APP_TOKEN")
    table_id = os.environ.get("FEISHU_TABLE_ID")
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    if not all([app_id, app_secret, app_token, table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整，请检查飞书相关配置和 Cookies")
        
    return app_id, app_secret, app_token, table_id, json.loads(s_cookies)

# === 核心逻辑 1: 获取飞书 Tenant Access Token ===
def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code == 200:
        return resp.json().get("tenant_access_token")
    else:
        raise Exception(f"获取飞书 Token 失败: {resp.text}")

# === 核心逻辑 2: 解析通知文本 ===
def parse_notification(text):
    """
    将 "Yuanke Lu submitted an item to Unit 3 Homework" 拆解
    返回: (学生姓名, 作业名称, 状态)
    """
    # 正则表达式：匹配 [名字] [动词] an item to [作业名]
    # (.*?) 是非贪婪匹配，防止把名字吃多了
    pattern = r"^(.*?) (submitted|resubmitted) an item to (.*)$"
    match = re.search(pattern, text, re.IGNORECASE)
    
    if match:
        student_name = match.group(1).strip()
        status = match.group(2).capitalize() # Submitted / Resubmitted
        assignment_name = match.group(3).strip()
        
        # 处理时间后缀 (Schoology有时会在作业名后面带日期，如 "...Homework Jan 25 at 4pm")
        # 简单处理：如果作业名太长且包含 " at ", 可以尝试截断，或者保留原样
        # 这里暂时保留原样，保证准确
        return student_name, assignment_name, status
    else:
        # 如果格式不标准，就只好把全名当名字，作业名留空
        return text, "Unknown Assignment", "Unknown"

# === 核心逻辑 3: 写入飞书多维表格 ===
def save_to_feishu(token, app_token, table_id, records):
    if not records:
        return
    
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # 构造飞书需要的格式
    feishu_records = []
    for row in records:
        feishu_records.append({
            "fields": {
                "学生姓名": row['student'],
                "作业名称": row['assignment'],
                "提交状态": row['status'],
                "原始通知": row['raw_text'],
                "提交时间": int(datetime.now().timestamp() * 1000), # 飞书需要毫秒时间戳
                "作业链接": {
                    "text": "点击查看作业",
                    "link": row['link']
                },
                "唯一ID": row['unique_id'] # 用于去重
            }
        })

    payload = {"records": feishu_records}
    resp = requests.post(url, json=payload, headers=headers)
    
    if resp.status_code == 200 and resp.json().get("code") == 0:
        print(f">>> 成功写入 {len(records)} 条数据到飞书！")
    else:
        print(f"!!! 写入飞书失败: {resp.text}")

# === 核心逻辑 4: 检查飞书已有数据 (去重) ===
def get_existing_ids(token, app_token, table_id):
    # 我们只拉取 "唯一ID" 这一列
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"field_names": '["唯一ID"]', "page_size": 500} # 一次拿500条够了
    
    resp = requests.get(url, headers=headers, params=params)
    existing_set = set()
    
    if resp.status_code == 200:
        data = resp.json().get("data", {}).get("items", [])
        for item in data:
            uid = item.get("fields", {}).get("唯一ID")
            if uid:
                existing_set.add(str(uid))
    return existing_set

def start_cloud_scraper():
    print(">>> 启动飞书版云端爬虫...")
    
    try:
        app_id, app_secret, app_token, table_id, s_cookies = get_env_config()
        
        # 获取 Token
        feishu_token = get_feishu_token(app_id, app_secret)
        print(">>> 飞书 API 连接成功")
        
        # 获取已有 ID 用于去重
        existing_ids = get_existing_ids(feishu_token, app_token, table_id)
        print(f">>> 飞书中已有记录: {len(existing_ids)} 条")

    except Exception as e:
        print(f"初始化配置失败: {e}")
        return

    # 启动浏览器
    print(">>> [Step 2] 启动浏览器...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        # 注入 Cookie 并访问
        print(">>> [Step 3] 注入 Schoology 凭证...")
        driver.get(LOGIN_URL)
        time.sleep(3)
        for cookie in s_cookies:
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try: driver.add_cookie(cookie)
            except: pass
        
        print(f">>> [Step 4] 访问通知页...")
        driver.get(NOTIFICATION_URL)
        time.sleep(10)

        if "login" in driver.current_url.lower():
            print("!!! ERROR: Schoology Cookie 失效")
            return

        # 点击加载更多
        for i in range(2):
            try:
                more_btns = driver.find_elements(By.CSS_SELECTOR, "li.notif-more a")
                if more_btns:
                    driver.execute_script("arguments[0].click();", more_btns[0])
                    time.sleep(5)
                else: break
            except: break

        # 扫描内容
        print(">>> [Step 6] 提取数据...")
        potential_items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not potential_items:
            potential_items = driver.find_elements(By.TAG_NAME, "li")

        new_records = []
        keywords = ["submitted", "resubmitted", "submission"]

        for item in potential_items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not raw_text: continue
                
                # 关键词检查
                if not any(k in raw_text.lower() for k in keywords):
                    continue

                # 生成一个简单的哈希ID (利用文本内容)，用于去重
                # 注意：如果同一天同一个学生交同一个作业两次，Raw Text 是一样的。
                # 飞书去重依赖这个 ID
                unique_id = str(hash(raw_text))

                if unique_id in existing_ids:
                    continue

                # 提取链接
                link_url = ""
                try:
                    links = item.find_elements(By.TAG_NAME, "a")
                    for l in links:
                        href = l.get_attribute("href")
                        if href and ("/assignment/" in href or "/assessment/" in href):
                            link_url = href
                            break
                except: pass

                # === 解析数据 (提取姓名、作业) ===
                student, assignment, status = parse_notification(raw_text)
                
                print(f"发现新数据: {student} -> {assignment}")
                
                new_records.append({
                    "student": student,
                    "assignment": assignment,
                    "status": status,
                    "raw_text": raw_text,
                    "link": link_url,
                    "unique_id": unique_id
                })
                
                existing_ids.add(unique_id)

            except: continue

        # 写入飞书
        if new_records:
            save_to_feishu(feishu_token, app_token, table_id, new_records)
        else:
            print(">>> 暂无新数据。")

    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()