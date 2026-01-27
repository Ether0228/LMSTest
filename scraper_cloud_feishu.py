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

# ================= 配置区域 (改为默认值) =================
LOGIN_URL = "https://queenscanada.schoology.com"
NOTIFICATION_URL = "https://queenscanada.schoology.com/home/notifications"
# ======================================================

def get_env_config():
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    table_id = os.environ.get("FEISHU_TABLE_ID", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    # === 新增：读取动态参数 ===
    # 1. 回溯日期：如果有传这个变量就用，没传就默认只回溯到昨天
    default_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    target_date_str = os.environ.get("TARGET_DATE", default_date)
    
    # 2. 最大翻页数：如果有传就用，没传默认只翻 2 页 (日常模式)
    max_clicks = int(os.environ.get("MAX_PAGES", "2"))

    if not all([app_id, app_secret, app_token, table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
    
    return app_id, app_secret, app_token, table_id, json.loads(s_cookies), target_date_str, max_clicks

# ... (中间的 get_feishu_token, parse_time_from_text, parse_notification_full, save_to_feishu, get_existing_ids 函数保持不变，直接复制之前的即可) ...
# 为了篇幅，我这里省略中间辅助函数，请务必保留原有的这些函数！
# ... (中间函数省略) ...

# === 必须要复制保留的中间函数 (与上一版相同) ===
def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    if resp.json().get("code") == 0: return resp.json().get("tenant_access_token")
    else: raise Exception(f"获取Token失败: {resp.text}")

def parse_time_from_text(text):
    time_pattern = r" ((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))$"
    match_time = re.search(time_pattern, text, re.IGNORECASE)
    if not match_time: return None
    try:
        now = datetime.now()
        date_part, time_part = match_time.group(1), match_time.group(2)
        full_time_str = f"{date_part} {time_part}"
        if "Today" in date_part:
            dt_obj = datetime.combine(now.date(), datetime.strptime(time_part, "%I:%M %p").time())
        elif "Yesterday" in date_part:
            dt_obj = datetime.combine(now.date() - timedelta(days=1), datetime.strptime(time_part, "%I:%M %p").time())
        else:
            try: dt_obj = datetime.strptime(full_time_str, "%b %d, %Y %I:%M %p")
            except: 
                dt_obj = datetime.strptime(full_time_str, "%b %d %I:%M %p").replace(year=now.year)
                if now.month == 1 and dt_obj.month == 12: dt_obj = dt_obj.replace(year=now.year - 1)
        return dt_obj
    except: return None

def parse_notification_full(text):
    timestamp_ms = int(datetime.now().timestamp() * 1000)
    dt_obj = parse_time_from_text(text)
    clean_text_end = len(text)
    if dt_obj:
        timestamp_ms = int(dt_obj.timestamp() * 1000)
        match = re.search(r" ((?:Jan|Feb|Today|Yesterday).*)$", text, re.IGNORECASE)
        if match: clean_text_end = match.start()
    main_text = text[:clean_text_end].strip()
    match_body = re.search(r"^(.*?) (submitted|resubmitted) an item to (.*)$", main_text, re.IGNORECASE)
    if match_body: return match_body.group(1).strip(), match_body.group(3).strip(), match_body.group(2).capitalize(), timestamp_ms
    else: return main_text, "Unknown", "Unknown", timestamp_ms

def save_to_feishu(token, app_token, table_id, records):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        feishu_records = [{"fields": {"学生姓名": r['student'], "作业名称": r['assignment'], "提交状态": r['status'], "原始通知": r['raw_text'], "提交时间": r['timestamp'], "作业链接": {"text": "查看作业", "link": r['link']}, "唯一ID": r['unique_id']}} for r in batch]
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
# ========================================================


def start_cloud_scraper():
    try:
        # 获取配置（包括动态参数）
        app_id, app_secret, app_token, table_id, s_cookies, target_date_str, max_clicks = get_env_config()
        
        print(f">>> 模式启动: 目标日期 [{target_date_str}], 最大翻页 [{max_clicks}]")
        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
        
        token = get_feishu_token(app_id, app_secret)
        existing_ids = get_existing_ids(token, app_token, table_id)
        print(f">>> 飞书已有记录: {len(existing_ids)} 条")
    except Exception as e:
        print(f"初始化失败: {e}")
        return

    # 启动浏览器
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

        if "login" in driver.current_url.lower():
            print("!!! ERROR: Cookie 失效")
            return

        # === 动态循环翻页 ===
        click_count = 0
        
        while click_count < max_clicks: # 使用变量控制
            try:
                # 检查日期决定是否提前停止
                items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
                if not items: items = driver.find_elements(By.TAG_NAME, "li")
                
                if items:
                    last_text = items[-1].text
                    last_date_obj = parse_time_from_text(last_text)
                    if last_date_obj and last_date_obj < target_date_obj:
                        print(f">>> 页面日期 ({last_date_obj.strftime('%Y-%m-%d')}) 早于目标日期，停止翻页。")
                        break
            except: pass

            try:
                print(f">>> 翻页: {click_count + 1}/{max_clicks}")
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a")))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(4)
                click_count += 1
            except:
                print(">>> 到底了，停止翻页。")
                break

        # === 抓取 ===
        print(">>> 扫描数据...")
        final_items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not final_items: final_items = driver.find_elements(By.TAG_NAME, "li")
        
        new_records = []
        keywords = ["submitted", "resubmitted", "submission"]

        for item in final_items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not raw_text or not any(k in raw_text.lower() for k in keywords): continue

                unique_id = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
                if unique_id in existing_ids: continue

                link_url = ""
                try:
                    links = item.find_elements(By.TAG_NAME, "a")
                    for l in links:
                        href = l.get_attribute("href")
                        if href and ("/assignment/" in href or "/assessment/" in href):
                            link_url = href
                            break
                except: pass

                student, assignment, status, timestamp = parse_notification_full(raw_text)
                item_date = datetime.fromtimestamp(timestamp / 1000)
                
                # 日期筛选
                if item_date < target_date_obj: continue

                print(f"捕获: {student} | {item_date.strftime('%Y-%m-%d')}")
                new_records.append({
                    "student": student, "assignment": assignment, "status": status,
                    "raw_text": raw_text, "link": link_url, "unique_id": unique_id, "timestamp": timestamp
                })
                existing_ids.add(unique_id)
            except: continue

        if new_records:
            save_to_feishu(token, app_token, table_id, new_records)
            print(">>> 完成！")
        else:
            print(">>> 无新数据。")

    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()
