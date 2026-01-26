import os
import json
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
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
    g_json = os.environ.get("GDRIVE_JSON")
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    if not g_json or not s_cookies:
        raise ValueError("GitHub Secrets 缺失 GDRIVE_JSON 或 SCHOOLOGY_COOKIES")
    try:
        return json.loads(g_json), json.loads(s_cookies)
    except json.JSONDecodeError as e:
        print("JSON 解析失败，请检查 Secret 格式。")
        raise e

def normalize_text(text):
    """清理文本，使其更易于比对"""
    return " ".join(text.split()).strip()

def start_cloud_scraper():
    print(">>> 启动云端爬虫流程...")
    g_creds, s_cookies = get_env_config()

    # 1. 连接 Google Sheets
    print(">>> [Step 1] 连接数据库...")
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(g_creds, scope)
    client = gspread.authorize(creds)
    
    sh = client.open("Schoology_Data")
    # 优先找 Submissions 表，找不到就用第一张表
    try:
        sheet = sh.worksheet("Submissions")
        print(">>> 已连接到 'Submissions' 工作表")
    except:
        sheet = sh.sheet1
        print(">>> 未找到 'Submissions'，已连接到第一张工作表 (Sheet1)")
    
    # 读取旧数据并归一化处理
    print(">>> 正在读取旧数据以进行去重...")
    raw_col_2 = sheet.col_values(2)
    existing_set = {normalize_text(t) for t in raw_col_2}
    print(f">>> 数据库中已有 {len(existing_set)} 条记录。")

    # 2. 配置无头浏览器
    print(">>> [Step 2] 启动浏览器...")
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        # 3. 注入 Cookie
        print(">>> [Step 3] 注入凭证...")
        driver.get(LOGIN_URL)
        time.sleep(3)
        for cookie in s_cookies:
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try: driver.add_cookie(cookie)
            except: pass
        
        # 4. 访问通知页
        print(f">>> [Step 4] 访问通知页: {NOTIFICATION_URL}")
        driver.get(NOTIFICATION_URL)
        time.sleep(5)

        if "login" in driver.current_url.lower():
            print("!!! ERROR: Cookie 可能已失效!")
            driver.save_screenshot("debug_login_error.png")
            return

        # 5. 加载更多
        for i in range(2):
            try:
                more_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a"))
                )
                print(f">>> 点击加载更多 (第 {i+1} 次)...")
                driver.execute_script("arguments[0].click();", more_btn)
                time.sleep(4)
            except:
                break

        # 6. 抓取逻辑
        print(">>> [Step 6] 扫描通知列表...")
        # 获取所有通知容器
        elements = driver.find_elements(By.XPATH, "//div[contains(@class, 's-edge-feed')]//div[contains(@class, 'feed-body')]")
        print(f">>> 页面上共发现 {len(elements)} 条通知内容。")
        
        new_rows = []
        keywords = ["submitted", "resubmitted", "submission"]

        for elem in elements:
            raw_text = elem.text
            norm_text = normalize_text(raw_text)
            
            # 如果文本为空，跳过
            if not norm_text:
                continue

            extracted_url = ""
            try:
                # 寻找该通知内的作业链接
                links = elem.find_elements(By.TAG_NAME, "a")
                for l in links:
                    href = l.get_attribute("href")
                    if href and ("/assignment/" in href or "/assessment/" in href):
                        extracted_url = href
                        break
            except:
                pass

            # 匹配逻辑：关键词存在 且 数据库里没有
            has_kw = any(k in norm_text.lower() for k in keywords)
            is_new = norm_text not in existing_set

            if has_kw and is_new:
                print(f"找到新提交: {norm_text[:40]}...")
                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                new_rows.append([current_time, raw_text.replace("\n", " "), extracted_url])
                existing_set.add(norm_text) # 防止单次运行重复

        # 7. 写入 Google Sheets
        if new_rows:
            print(f">>> 正在将 {len(new_rows)} 条数据写入云端...")
            sheet.append_rows(new_rows)
            print(">>> 写入成功！")
        else:
            print(">>> 暂无新通知 (所有符合条件的通知已在数据库中)。")

    except Exception as e:
        print(f"ERROR: 运行异常: {e}")
        driver.save_screenshot("debug_error.png")
    finally:
        driver.quit()
        print(">>> 流程结束。")

if __name__ == "__main__":
    start_cloud_scraper()  # 确保这里的名字和上面定义的 def 名字一致
