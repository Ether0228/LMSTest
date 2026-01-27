import hashlib
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
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    table_id = os.environ.get("FEISHU_TABLE_ID", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    if not all([app_id, app_secret, app_token, table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
        
    return app_id, app_secret, app_token, table_id, json.loads(s_cookies)

def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    if resp.json().get("code") == 0:
        return resp.json().get("tenant_access_token")
    else:
        raise Exception(f"获取Token失败: {resp.text}")

# === 核心升级：智能解析时间与作业名 ===
def parse_notification_smart(text):
    """
    输入: "Yifei Tao submitted an item to Unit 3 Lesson 1 Jan 27 at 12:25 am"
    输出: (Yifei Tao, Unit 3 Lesson 1, Submitted, 1706243100000)
    """
    
    # 1. 定义 Schoology 的时间后缀正则
    # 匹配: Jan 27 at 12:25 am | Today at 2:00 pm | Yesterday at ...
    # 包含可选的年份 (, 2025)
    time_pattern = r" ((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))$"
    
    match_time = re.search(time_pattern, text, re.IGNORECASE)
    
    timestamp_ms = int(datetime.now().timestamp() * 1000) # 默认当前时间
    clean_text_end_index = len(text)
    
    # 如果找到了时间后缀
    if match_time:
        date_part = match_time.group(1) # Jan 27 或 Today
        time_part = match_time.group(2) # 12:25 am
        full_time_str = f"{date_part} {time_part}"
        clean_text_end_index = match_time.start() # 记录时间开始的位置，用于截断作业名
        
        # --- 时间字符串转对象 ---
        try:
            now = datetime.now()
            dt_obj = None
            
            if "Today" in date_part:
                # 处理 Today at 12:00 am
                time_obj = datetime.strptime(time_part, "%I:%M %p")
                dt_obj = datetime.combine(now.date(), time_obj.time())
            
            elif "Yesterday" in date_part:
                # 处理 Yesterday at ...
                time_obj = datetime.strptime(time_part, "%I:%M %p")
                dt_obj = datetime.combine(now.date() - timedelta(days=1), time_obj.time())
            
            else:
                # 处理 Jan 27 at 12:25 am
                # 先尝试带年份的格式
                try:
                    dt_obj = datetime.strptime(full_time_str, "%b %d, %Y %I:%M %p")
                except:
                    # 如果没有年份，默认为当前年份
                    dt_obj = datetime.strptime(full_time_str, "%b %d %I:%M %p")
                    dt_obj = dt_obj.replace(year=now.year)
                    
                    # 跨年修正：如果现在是1月，抓到了12月的作业，说明是去年的
                    if now.month == 1 and dt_obj.month == 12:
                        dt_obj = dt_obj.replace(year=now.year - 1)

            # 转为毫秒时间戳
            timestamp_ms = int(dt_obj.timestamp() * 1000)
            
        except Exception as e:
            print(f"时间解析微调失败，使用当前时间: {e}")

    # 2. 解析前面的主体：学生 + 动作 + 作业名
    # 只解析到时间出现之前的部分 text[:clean_text_end_index]
    main_text = text[:clean_text_end_index].strip()
    
    name_pattern = r"^(.*?) (submitted|resubmitted) an item to (.*)$"
    match_body = re.search(name_pattern, main_text, re.IGNORECASE)
    
    if match_body:
        student = match_body.group(1).strip()
        status = match_body.group(2).capitalize()
        assignment = match_body.group(3).strip()
        return student, assignment, status, timestamp_ms
    else:
        # 匹配失败兜底
        return main_text, "Unknown", "Unknown", timestamp_ms

def save_to_feishu(token, app_token, table_id, records):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    
    feishu_records = []
    for row in records:
        feishu_records.append({
            "fields": {
                "学生姓名": row['student'],
                "作业名称": row['assignment'],
                "提交状态": row['status'],
                "原始通知": row['raw_text'],
                "提交时间": row['timestamp'], # 使用解析出的真实提交时间
                "作业链接": {"text": "查看作业", "link": row['link']},
                "唯一ID": row['unique_id']
            }
        })

    resp = requests.post(url, json={"records": feishu_records}, headers=headers)
    if resp.json().get("code") == 0:
        print(f">>> 成功同步 {len(records)} 条数据到飞书")
    else:
        print(f"!!! 飞书写入错误: {resp.text}")

def get_existing_ids(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params={"field_names": '["唯一ID"]', "page_size": 500})
    ids = set()
    if resp.json().get("code") == 0:
        for item in resp.json().get("data", {}).get("items", []):
            val = item.get("fields", {}).get("唯一ID")
            if val: ids.add(str(val))
    return ids

def start_cloud_scraper():
    print(">>> 启动智能解析版爬虫...")
    try:
        app_id, app_secret, app_token, table_id, s_cookies = get_env_config()
        token = get_feishu_token(app_id, app_secret)
        existing_ids = get_existing_ids(token, app_token, table_id)
        print(f">>> 飞书已有记录: {len(existing_ids)}")
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

        # 翻页逻辑
        for i in range(2):
            try:
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a")))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(4)
            except: break

        # 抓取逻辑
        potential_items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not potential_items: potential_items = driver.find_elements(By.TAG_NAME, "li")
        
        new_records = []
        keywords = ["submitted", "resubmitted", "submission"]

        for item in potential_items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not raw_text or not any(k in raw_text.lower() for k in keywords): continue

                # 生成ID
                unique_id = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
                if unique_id in existing_ids: continue

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

                # === 智能解析 ===
                student, assignment, status, timestamp = parse_notification_smart(raw_text)
                
                print(f"新: {student} | 作业: {assignment} | 时间: {datetime.fromtimestamp(timestamp/1000)}")
                
                new_records.append({
                    "student": student,
                    "assignment": assignment,
                    "status": status,
                    "raw_text": raw_text,
                    "link": link_url,
                    "unique_id": unique_id,
                    "timestamp": timestamp
                })
                existing_ids.add(unique_id)
            except: continue

        if new_records:
            save_to_feishu(token, app_token, table_id, new_records)
        else:
            print(">>> 无新数据")

    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()
