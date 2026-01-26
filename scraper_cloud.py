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
        raise ValueError("错误：GitHub Secrets 缺失 GDRIVE_JSON 或 SCHOOLOGY_COOKIES")
        
    try:
        return json.loads(g_json), json.loads(s_cookies)
    except json.JSONDecodeError as e:
        print("JSON 解析失败，请检查 Secret 格式。")
        raise e

def start_cloud_scraper():
    print(">>> 启动云端爬虫流程...")
    g_creds, s_cookies = get_env_config()

    # 1. 连接 Google Sheets
    print(">>> [Step 1] 连接数据库...")
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(g_creds, scope)
    client = gspread.authorize(creds)
    
    # 【注意】请确保你的表格名字是 Schoology_Data，工作表名字是 Submissions
    sh = client.open("Schoology_Data")
    sheet = sh.worksheet("Submissions")
    
    # 读取旧数据去重 (第2列是通知内容)
    existing_set = set(sheet.col_values(2))

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
            try:
                driver.add_cookie(cookie)
            except:
                pass
        
        # 4. 访问通知页
        print(f">>> [Step 4] 正在获取通知: {NOTIFICATION_URL}")
        driver.get(NOTIFICATION_URL)
        time.sleep(7) # 增加等待时间

        # --- 调试信息 ---
        print(f"DEBUG: 页面标题 - {driver.title}")
        print(f"DEBUG: 当前URL - {driver.current_url}")
        driver.save_screenshot("debug_view.png") # 保存截图
        # ----------------

        if "login" in driver.current_url.lower() or "signin" in driver.current_url.lower():
            print("!!! ERROR: Cookie 可能已失效，被重定向到了登录页!")
            return

        # 5. 循环加载更多 (处理翻页)
        for i in range(2):
            try:
                # 定位你之前发现的 li.notif-more a
                more_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "li.notif-more a"))
                )
                print(f">>> 点击加载更多 (第 {i+1} 次)...")
                driver.execute_script("arguments[0].click();", more_button)
                time.sleep(4)
            except:
                break

        # 6. 抓取逻辑
        print(">>> [Step 6] 正在扫描通知列表...")
        elements = driver.find_elements(By.XPATH, "//div[contains(@class, 's-edge-feed')]//div[contains(@class, 'feed-body')]")
        
        new_rows = []
        keywords = ["submitted", "resubmitted", "submission"]

        for elem in elements:
            text = elem.text.strip().replace("\n", " ")
            
            # 提取作业链接
            extracted_url = ""
            try:
                link_elem = elem.find_element(By.TAG_NAME, "a")
                extracted_url = link_elem.get_attribute("href")
            except:
                pass

            # 筛选：关键词 + 不在旧数据里
            if any(k in text.lower() for k in keywords) and (text not in existing_set):
                print(f"发现新提交: {text[:30]}")
                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                new_rows.append([current_time, text, extracted_url])
                existing_set.add(text) # 防止单次运行重复

        # 7. 写入 Google Sheets
        if new_rows:
            print(f">>> 成功写入 {len(new_rows)} 条数据到 Google Sheets")
            sheet.append_rows(new_rows)
        else:
            print(">>> 暂无新通知。")

    except Exception as e:
        print(f"ERROR: 运行中发生错误: {e}")
    finally:
        driver.quit()
        print(">>> 流程结束。")

if __name__ == "__main__":
    start_cloud_scraper()
