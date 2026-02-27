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
    
    # 获取关联表 ID
    roster_tid = os.environ.get("FEISHU_ROSTER_TABLE_ID", "").strip()
    lib_tid = os.environ.get("FEISHU_LIB_TABLE_ID", "").strip()
    
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    # 动态参数处理
    # 默认回溯到昨天
    default_date = (datetime.utcnow() + timedelta(hours=8) - timedelta(days=1)).strftime("%Y-%m-%d")
    target_date_raw = os.environ.get("TARGET_DATE", "").strip()
    target_date = target_date_raw if target_date_raw else default_date
    
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
        raise Exception(f"获取Token失败: {resp.text}")

def clean_schoology_url(url):
    if not url: return ""
    match = re.search(r'(https://.*?/(?:assignment|assessment|discussion)/\d+)', url)
    return match.group(1) if match else url

# === 修复：更严格的时间解析 ===
def parse_time_to_str(text):
    """
    辅助函数：仅负责把时间文本转为标准格式
    """
    try:
        # 定义标准时间格式正则
        pattern = r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))"
        match = re.search(pattern, text, re.IGNORECASE)
        
        # 如果不是标准格式，直接返回当前时间 (兜底)
        if not match:
            return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y/%m/%d %H:%M")

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
                # 带年份
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
    """
    解析通知，分离作业名和时间
    """
    # 1. 定义极其严格的时间后缀正则 (必须包含 at + 时间点)
    # 这会匹配: " Jan 28 at 8:57 pm"
    # 但不会匹配: " January 28th" (因为后面没有 at)
    strict_time_suffix = r"\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:,\s+\d{4})?|Today|Yesterday)\s+at\s+(\d{1,2}:\d{2}\s+(?:am|pm))"
    
    # 2. 查找所有的匹配项
    matches = list(re.finditer(strict_time_suffix, text, re.IGNORECASE))
    
    clean_text_end = len(text)
    time_text_segment = "" # 用于提取时间的部分
    
    if matches:
        # 【关键】取列表里的【最后一个】匹配项作为分割点
        # 即使作业名里有 "Jan 1 at 2pm"，Schoology 的提交时间肯定是在字符串的最末尾
        last_match = matches[-1]
        clean_text_end = last_match.start()
        time_text_segment = last_match.group(0).strip() # 取出时间文本用于解析
    else:
        # 如果没找到标准时间，就不切断作业名，避免误伤
        time_text_segment = text 

    # 3. 解析时间字符串
    time_str = parse_time_to_str(time_text_segment)

    # 4. 截取主体文本
    main_text = text[:clean_text_end].strip()
    
    # 5. 拆解学生和作业名
    name_pattern = r"^(.*?) (submitted|resubmitted) an item to (.*)$"
    m = re.search(name_pattern, main_text, re.IGNORECASE)
    
    if m:
        return m.group(1).strip(), m.group(3).strip(), m.group(2).capitalize(), time_str
    else:
        # 如果匹配失败，说明作业名可能包含特殊字符
        # 此时直接返回 main_text 作为作业名
        return "Unknown", main_text, "Unknown", time_str

# === 辅助：加载映射表 ===
def get_feishu_mapping(token, app_token, table_id, key_field_name):
    if not table_id: return {}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    mapping = {}
    page_token = None
    
    print(f">>> 正在加载表 [{table_id}]...")
    while True:
        params = {"page_size": 1000}
        if page_token: params["page_token"] = page_token
        try:
            resp = requests.get(url, headers=headers, params=params).json()
            if resp.get("code") != 0: break
            for item in resp.get("data", {}).get("items", []):
                rec_id = item.get("record_id")
                fields = item.get("fields", {})
                val = fields.get(key_field_name)
                # 处理链接字段
                if isinstance(val, dict) and "link" in val: val = val["link"]
                elif isinstance(val, list): val = str(val[0]) if val else ""
                
                if val:
                    val_str = str(val).strip()
                    if "http" in val_str: val_str = clean_schoology_url(val_str)
                    mapping[val_str] = rec_id
            if not resp.get("data", {}).get("has_more"): break
            page_token = resp.get("data", {}).get("page_token")
        except: break
    return mapping

def add_assignment_to_lib(token, app_token, lib_table_id, name, clean_url):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{lib_table_id}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    fields = {
        "作业名称": name,
        "作业链接": clean_url,
        "作业性质": "✅ 必交"
    }

    try:
        response = requests.post(url, json={"fields": fields}, headers=headers)
        resp_json = response.json()
        if resp_json.get("code") == 0:
            rec_id = resp_json.get("data", {}).get("record", {}).get("record_id")
            print(f">>> [自动建档] 成功: {name}")
            return rec_id
        else:
            print(f"!!! [自动建档] 失败! 错误码: {resp_json.get('code')}, 原因: {resp_json.get('msg')}")
            print(f"DEBUG 详情: {resp_json}")
            return None
    except Exception as e:
        print(f"!!! [自动建档] 网络请求异常: {e}")
        return None

def save_to_feishu_v2(token, app_token, table_id, records):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    
    success_count = 0
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        payload = [{"fields": r} for r in batch]
        
        response = requests.post(url, json={"records": payload}, headers=headers)
        resp_json = response.json()
        
        if resp_json.get("code") == 0:
            success_count += len(batch)
        else:
            # 这里会打印出到底是哪个字段导致的权限拒绝
            print(f"!!! 批次写入失败: {resp_json.get('msg')}")
            print(f"DEBUG 详情: {json.dumps(resp_json.get('error', {}))}")
            
    if success_count > 0:
        print(f">>> 实际成功写入 {success_count} 条数据")

def start_cloud_scraper():
    print(">>> 启动调试版爬虫...")
    try:
        app_id, app_secret, app_token, table_id, roster_tid, lib_tid, s_cookies, target_date, max_pages = get_env_config()
        
        # 转换目标日期对象
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        print(f">>> 目标回溯日期: {target_date} (凡是早于此日期的将被忽略)")
        
        token = get_feishu_token(app_id, app_secret)
        
        roster_map = get_feishu_mapping(token, app_token, roster_tid, "学生姓名")
        lib_map = get_feishu_mapping(token, app_token, lib_tid, "作业链接")
        existing_ids = set(get_feishu_mapping(token, app_token, table_id, "唯一ID").keys())
        
        print(f">>> 准备就绪: 库中有 {len(lib_map)} 个作业, 已存 {len(existing_ids)} 条记录")

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
                # 检查日期决定是否停止
                # 简单抽样检查当前页最后一条
                items_check = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
                if items_check:
                    last_text = items_check[-1].text
                    last_time_str = parse_time_to_str(last_text)
                    try:
                        last_dt = datetime.strptime(last_time_str, "%Y/%m/%d %H:%M")
                        # 比较日期部分
                        if last_dt.date() < target_dt.date():
                            print(f">>> 当前页数据已早于目标日期 ({last_time_str})，停止翻页。")
                            break
                    except: pass

                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a")))
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(4)
            except: break

        items = driver.find_elements(By.CSS_SELECTOR, ".s-edge-feed-item")
        if not items: items = driver.find_elements(By.TAG_NAME, "li")
        
        print(f">>> 扫描到 {len(items)} 条通知，开始筛选...")
        
        new_records = []
        for item in items:
            try:
                raw_text = item.text.strip().replace("\n", " ")
                if not raw_text: continue
                if "comment" in raw_text.lower(): continue
                if not any(k in raw_text.lower() for k in ["submitted", "resubmitted"]): continue
                
                unique_id = hashlib.md5(raw_text.encode('utf-8')).hexdigest()
                
                # === 调试日志 1: 检查去重 ===
                if unique_id in existing_ids:
                    # print(f"[跳过] 已存在: {raw_text[:30]}...") # 调试时可以打开
                    continue

                clean_link = ""
                link_url = ""
                try:
                    all_links = item.find_elements(By.TAG_NAME, "a")
                    for l in all_links:
                        href = l.get_attribute("href")
                        if href and ("/assignment/" in href or "/assessment/" in href):
                            link_url = href
                            clean_link = clean_schoology_url(href)
                            break
                except: pass
                
                # === 调试日志 2: 检查链接 ===
                if not clean_link:
                    print(f"[跳过] 无链接: {raw_text[:30]}...")
                    continue

                student, assign, status, time_str = parse_notification_simple(raw_text)
                
                # === 调试日志 3: 检查日期过滤 ===
                try:
                    item_dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M")
                    # 只比较日期部分，忽略时间，防止同一天被误删
                    if item_dt.date() < target_dt.date():
                        # print(f"[跳过] 日期过早: {time_str} < {target_date}")
                        continue
                except:
                    print(f"[跳过] 日期解析失败: {time_str}")
                    continue

                # 自动建档与关联
                assign_rec_id = lib_map.get(clean_link)
                if not assign_rec_id:
                    print(f">>> 自动建档: {assign}")
                    assign_rec_id = add_assignment_to_lib(token, app_token, lib_tid, assign, clean_link)
                    if assign_rec_id: lib_map[clean_link] = assign_rec_id
                
                student_rec_id = roster_map.get(student)

                fields = {
                    "学生姓名": student,
                    "作业名称": assign,
                    "提交状态": status,
                    "原始通知": raw_text,
                    "提交时间": time_str,
                    "作业链接": {"text": link_url, "link": link_url}, # 修复：同时设置 text 和 link
                    "唯一ID": unique_id
                }
                
                if assign_rec_id: fields["关联作业"] = [assign_rec_id]
                if student_rec_id: fields["关联学生"] = [student_rec_id]

                print(f"✅ 捕获: {student} | {assign} | {time_str} | 关联作业={'✓' if assign_rec_id else '✗'} | 关联学生={'✓' if student_rec_id else '✗'}")
                new_records.append(fields)
                existing_ids.add(unique_id)
            except Exception as e:
                print(f"!!! 单条处理出错: {e}")
                continue

        if new_records:
            save_to_feishu_v2(token, app_token, table_id, new_records)
            print(f">>> 成功写入 {len(new_records)} 条数据")
        else:
            print(">>> 筛选后无符合条件的新数据")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()

