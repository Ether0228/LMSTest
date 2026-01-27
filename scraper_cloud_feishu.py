import os
import json
import time
import requests
import re
import hashlib
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
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    table_id = os.environ.get("FEISHU_TABLE_ID", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    default_date = (datetime.utcnow() + timedelta(hours=8) - timedelta(days=1)).strftime("%Y-%m-%d")
    target_date = os.environ.get("TARGET_DATE", default_date)
    # 先读取环境变量
    max_pages_env = os.environ.get("MAX_PAGES", "2")
    # 增加判断：如果环境变量是空字符串，则使用默认值 2
    max_pages = int(max_pages_env) if max_pages_env and max_pages_env.strip() else 2
    
    if not all([app_id, app_secret, app_token, table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
    return app_id, app_secret, app_token, table_id, json.loads(s_cookies), target_date, max_pages

def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    if resp.json().get("code") == 0:
        return resp.json().get("tenant_access_token")
    else:
        raise Exception(f"获取飞书Token失败: {resp.text}")

def clean_schoology_url(url):
    """
    清洗链接，只保留到 ID 为止
    例如: https://.../assignment/123456/info -> https://.../assignment/123456
    """
    if not url: return ""
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', url)
    if match:
        return match.group(1)
    return url

def parse_time_to_str(text):
    pattern = r" ((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))$"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")
    try:
        beijing_now = datetime.utcnow() + timedelta(hours=8)
        date_part, time_part = match.group(1), match.group(2)
        full_time_str = f"{date_part} {time_part}"
        dt_val = None
        if "Today" in date_part:
            dt_val = datetime.combine(beijing_now.date(), datetime.strptime(time_part, "%I:%M %p").time())
        elif "Yesterday" in date_part:
            dt_val = datetime.combine(beijing_now.date() - timedelta(days=1), datetime.strptime(time_part, "%I:%M %p").time())
        else:
            try:
                dt_val = datetime.strptime(full_time_str, "%b %d, %Y %I:%M %p")
            except:
                dt_val = datetime.strptime(full_time_str, "%b %d %I:%M %p").replace(year=beijing_now.year)
                if beijing_now.month == 1 and dt_val.month == 12:
                    dt_val = dt_val.replace(year=beijing_now.year - 1)
        return dt_val.strftime("%Y/%m/%d %H:%M")
    except: return text

def parse_notification_simple(text):
    time_str = parse_time_to_str(text)
    clean_text_end = len(text)
    match = re.search(r" ((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Today|Yesterday).*)$", text, re.IGNORECASE)
    if match: clean_text_end = match.start()
    main_text = text[:clean_text_end].strip()
    m = re.search(r"^(.*?) (submitted|resubmitted) an item to (.*)$", main_text, re.IGNORECASE)
    if m: return m.group(1).strip(), m.group(3).strip(), m.group(2).capitalize(), time_str
    else: return main_text, "Unknown", "Unknown", time_str

def save_to_feishu(token, app_token, table_id, records):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        feishu_records = []
        for row in batch:
            feishu_records.append({
                "fields": {
                    "学生姓名": row['student'],
                    "作业名称": row['assignment'],
                    "提交状态": row['status'],
                    "原始通知": row['raw_text'],
                    "提交时间": row['time_str'],
                    "作业链接": {"text": "查看作业", "link": row['link']}, # 这里已经是清洗过的
                    "唯一ID": row['unique_id']
                }
            })
        requests.post(url, json={"records": feishu_records}, headers=headers)

def get_existing_ids(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    ids = set()
    page_token = None
    while True:
        params = {"field_names": '["唯一ID"]', "page_size": 1000}
        if page_token: params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params)
        if resp.json().get("code") != 0: break
        data = resp.json().get("data", {})
        for item in data.get("items", []):
            val = item.get("fields", {}).get("唯一ID")
            if val: ids.add(str(val))
        if not data.get("has_more"): break
        page_token = data.get("page_token")
    return ids

def start_cloud_scraper():
    print(">>> 启动完整清洗版爬虫...")
    try:
        app_id, app_secret, app_token, table_id, s_cookies, target_date, max_pages = get_env_config()
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        token = get_feishu_token(app_id, app_secret)
        existing_ids = get_existing_ids(token, app_token, table_id)
        print(f">>> 飞书已有记录: {len(existing_ids)}")
    except Exception as e:
        print(f"初始化失败: {e}")
        return

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        driver.get(LOGIN_URL)
        time.sleep(3)
        for cookie in s_cookies:
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try: driver.add_cookie(cookie)
            except: pass
        
        driver.get(NOTIFICATION_URL)
        time.sleep(8)

        for i in range(max_pages):
            try:
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a")))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(5)
            except: break

        items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not items: items = driver.find_elements(By.TAG_NAME, "li")
        
        new_records = []
        for item in items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not any(k in raw_text.lower() for k in ["submitted", "submission"]): continue
                
                unique_id = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
                if unique_id in existing_ids: continue

                # 寻找并清洗链接
                link = ""
                try:
                    all_links = item.find_elements(By.TAG_NAME, "a")
                    for l in all_links:
                        href = l.get_attribute("href")
                        if href and ("/assignment/" in href or "/assessment/" in href):
                            link = clean_schoology_url(href)
                            break
                except: pass

                student, assign, status, time_str = parse_notification_simple(raw_text)
                
                item_dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M")
                if item_dt < target_dt: continue

                print(f"新数据: {student} | {time_str}")
                new_records.append({
                    "student": student, "assignment": assign, "status": status,
                    "raw_text": raw_text, "link": link, "unique_id": unique_id, "time_str": time_str
                })
                existing_ids.add(unique_id)
            except: continue

        if new_records:
            save_to_feishu(token, app_token, table_id, new_records)
            print(f">>> 成功写入 {len(new_records)} 条数据")
        else:
            print(">>> 无新数据")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()
