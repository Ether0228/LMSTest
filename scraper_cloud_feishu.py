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
    # 基础配置
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    # 三张表的 ID
    table_id = os.environ.get("FEISHU_TABLE_ID", "").strip()       # 提交记录表
    roster_tid = os.environ.get("FEISHU_ROSTER_TABLE_ID", "").strip() # 花名册表
    lib_tid = os.environ.get("FEISHU_LIB_TABLE_ID", "").strip()       # 作业库表
    
    # 动态参数
    default_date = (datetime.utcnow() + timedelta(hours=8) - timedelta(days=1)).strftime("%Y-%m-%d")
    target_date = os.environ.get("TARGET_DATE", "")
    target_date = target_date.strip() if target_date else default_date
    
    max_pages_raw = os.environ.get("MAX_PAGES", "").strip()
    max_pages = int(max_pages_raw) if max_pages_raw else 2
    
    if not all([app_id, app_secret, app_token, table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
        
    return app_id, app_secret, app_token, table_id, roster_tid, lib_tid, json.loads(s_cookies), target_date, max_pages

def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    if resp.json().get("code") == 0:
        return resp.json().get("tenant_access_token")
    else:
        raise Exception(f"获取飞书Token失败: {resp.text}")

def clean_schoology_url(url):
    """清洗链接，只保留到ID，用于比对"""
    if not url: return ""
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', url)
    return match.group(1) if match else url

# === 工具函数：加载辅助表映射 ===
def get_feishu_mapping(token, app_token, table_id, key_field_name):
    """
    读取指定表，返回 { "关键列内容": "record_id" } 的字典
    例如：{"Yuanke Lu": "rec123...", "https://.../123": "rec456..."}
    """
    if not table_id: return {}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    mapping = {}
    page_token = None
    
    print(f">>> 正在加载表 [{table_id}] 的映射数据...")
    while True:
        params = {"page_size": 1000}
        if page_token: params["page_token"] = page_token
        try:
            resp = requests.get(url, headers=headers, params=params).json()
            if resp.get("code") != 0: break
            
            for item in resp.get("data", {}).get("items", []):
                record_id = item.get("record_id")
                fields = item.get("fields", {})
                val = fields.get(key_field_name)
                
                # 处理链接类型的字段 (如果是List或Dict)
                if isinstance(val, dict) and "link" in val: val = val["link"]
                elif isinstance(val, list): val = str(val[0]) if val else ""
                
                if val:
                    # 如果看起来像链接，清洗一下再存
                    val_str = str(val).strip()
                    if "http" in val_str: val_str = clean_schoology_url(val_str)
                    mapping[val_str] = record_id
            
            if not resp.get("data", {}).get("has_more"): break
            page_token = resp.get("data", {}).get("page_token")
        except Exception as e:
            print(f"加载映射出错: {e}")
            break
    return mapping

# === 工具函数：自动添加新作业 ===
def add_assignment_to_lib(token, app_token, lib_table_id, name, clean_url):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{lib_table_id}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    
    # 注意：这里对应《作业库》的列名
    fields = {
        "作业名称": name,
        "作业链接": clean_url,
        "统计状态": "✅ 必交" # 默认值
    }
    
    try:
        resp = requests.post(url, json={"fields": fields}, headers=headers).json()
        if resp.get("code") == 0:
            rec_id = resp.get("data", {}).get("record", {}).get("record_id")
            print(f">>> [自动建档] 新作业已添加: {name}")
            return rec_id
        else:
            print(f"!!! 建档失败: {resp}")
            return None
    except: return None

def parse_time_to_str(text):
    """
    将 Jan 5 at 8:53 am 转换为字符串 2026/01/05 08:53
    """
    # === 修改点 1：正则变得更加严格 ===
    # 必须匹配到 Month ... at HH:MM am/pm 结构，才认为是时间
    # 这样就不会误判作业名里的 "January 28th" 了
    pattern = r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))"
    match = re.search(pattern, text, re.IGNORECASE)
    
    if not match:
        # 如果没找到标准时间格式，返回当前北京时间
        return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")

    try:
        beijing_now = datetime.utcnow() + timedelta(hours=8)
        date_part = match.group(1)
        time_part = match.group(2)
        full_time_str = f"{date_part} {time_part}"
        
        dt_val = None
        if "Today" in date_part:
            t = datetime.strptime(time_part, "%I:%M %p").time()
            dt_val = datetime.combine(beijing_now.date(), t)
        elif "Yesterday" in date_part:
            t = datetime.strptime(time_part, "%I:%M %p").time()
            dt_val = datetime.combine(beijing_now.date() - timedelta(days=1), t)
        else:
            try:
                # 尝试带年份
                dt_val = datetime.strptime(full_time_str, "%b %d, %Y %I:%M %p")
            except:
                # 默认今年
                dt_val = datetime.strptime(full_time_str, "%b %d %I:%M %p")
                dt_val = dt_val.replace(year=beijing_now.year)
                if beijing_now.month == 1 and dt_val.month == 12:
                    dt_val = dt_val.replace(year=beijing_now.year - 1)
        
        return dt_val.strftime("%Y/%m/%d %H:%M")
    except:
        return text

def parse_notification_simple(text):
    # 先解析出时间字符串
    time_str = parse_time_to_str(text)
    
    clean_text_end = len(text)
    
    # === 修改点 2：截断逻辑也同步变严格 ===
    # 寻找确切的时间后缀位置（必须包含 " at "）
    # 这里的正则和上面保持一致，确保只切掉真正的时间部分
    time_suffix_pattern = r"\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Today|Yesterday).*?\s+at\s+\d{1,2}:\d{2}\s+(?:am|pm))"
    
    # 使用 finditer 找所有的匹配项，取【最后一个】
    # 防止作业名里也有 "Jan 1 at 2:00 pm" 这种极罕见情况
    matches = list(re.finditer(time_suffix_pattern, text, re.IGNORECASE))
    
    if matches:
        last_match = matches[-1] # 取最后出现的那个时间作为系统时间
        clean_text_end = last_match.start()

    main_text = text[:clean_text_end].strip()
    
    name_pattern = r"^(.*?) (submitted|resubmitted) an item to (.*)$"
    m = re.search(name_pattern, main_text, re.IGNORECASE)
    
    if m:
        return m.group(1).strip(), m.group(3).strip(), m.group(2).capitalize(), time_str
    else:
        return main_text, "Unknown", "Unknown", time_str

def save_to_feishu_v2(token, app_token, table_id, records):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        # 包装 payload
        payload = [{"fields": r} for r in batch]
        requests.post(url, json={"records": payload}, headers=headers)

# === 主流程 ===
def start_cloud_scraper():
    print(">>> 启动全自动关联版爬虫...")
    try:
        app_id, app_secret, app_token, table_id, roster_tid, lib_tid, s_cookies, target_date, max_pages = get_env_config()
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        
        token = get_feishu_token(app_id, app_secret)
        
        # 1. 预加载映射
        # 注意：这里的 Key 必须和你飞书表里的列名内容对应
        # 花名册 Key: "学生姓名"
        roster_map = get_feishu_mapping(token, app_token, roster_tid, "学生姓名")
        # 作业库 Key: "作业链接" (注意我们把链接放在第二列，但名字叫"作业链接")
        lib_map = get_feishu_mapping(token, app_token, lib_tid, "作业链接")
        
        # 获取已有提交ID (用于去重)
        existing_ids = set(get_feishu_mapping(token, app_token, table_id, "唯一ID").keys())
        print(f">>> 初始化完成: 学生{len(roster_map)}, 作业{len(lib_map)}, 已存记录{len(existing_ids)}")

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
        if "login" in driver.current_url.lower(): return

        for i in range(max_pages):
            try:
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a")))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(4)
            except: break

        items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not items: items = driver.find_elements(By.TAG_NAME, "li")
        
        new_records = []
        for item in items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not raw_text: continue
                # 过滤逻辑
                if "comment" in raw_text.lower(): continue
                if not any(k in raw_text.lower() for k in ["submitted", "resubmitted"]): continue
                
                unique_id = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
                if unique_id in existing_ids: continue

                # 提取链接
                link = ""
                clean_link = ""
                try:
                    all_links = item.find_elements(By.TAG_NAME, "a")
                    for l in all_links:
                        href = l.get_attribute("href")
                        if href and ("/assignment/" in href or "/assessment/" in href):
                            link = href
                            clean_link = clean_schoology_url(href)
                            break
                except: pass
                
                if not clean_link: continue # 没链接没法关联，跳过

                student, assign, status, time_str = parse_notification_simple(raw_text)
                if datetime.strptime(time_str, "%Y/%m/%d %H:%M") < target_dt: continue

                # === 核心：处理关联 ===
                # 1. 查找作业ID，没有则自动创建
                assign_rec_id = lib_map.get(clean_link)
                if not assign_rec_id:
                    print(f">>> 新作业自动建档: {assign}")
                    assign_rec_id = add_assignment_to_lib(token, app_token, lib_tid, assign, clean_link)
                    if assign_rec_id:
                        lib_map[clean_link] = assign_rec_id # 更新内存映射
                
                # 2. 查找学生ID
                student_rec_id = roster_map.get(student)

                # 3. 组装数据 (直接带上关联)
                fields = {
                    "学生姓名": student,
                    "作业名称": assign,
                    "提交状态": status,
                    "原始通知": raw_text,
                    "提交时间": time_str,
                    "作业链接": {
                        "text": row['link'],  # <--- 关键：强制让显示的文字等于链接本身
                        "link": row['link']   # 实际跳转的地址
                    },
                    "唯一ID": unique_id
                }
                
                # 关联字段必须是列表 [id, id]
                if assign_rec_id: fields["关联作业"] = [assign_rec_id]
                if student_rec_id: fields["关联学生"] = [student_rec_id]

                print(f"新: {student} | {assign}")
                new_records.append(fields)
                existing_ids.add(unique_id)
            except: continue

        if new_records:
            save_to_feishu_v2(token, app_token, table_id, new_records)
            print(f">>> 成功写入 {len(new_records)} 条")
        else:
            print(">>> 无新数据")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()
