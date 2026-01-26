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

# 从 GitHub Secrets 读取配置
def get_env_config():
    g_json = os.environ.get("GDRIVE_JSON")
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    # 调试诊断
    if not g_json:
        raise ValueError("错误：环境变量 GDRIVE_JSON 为空！请检查 GitHub Secrets 设置。")
    if not s_cookies:
        raise ValueError("错误：环境变量 SCHOOLOGY_COOKIES 为空！请检查 GitHub Secrets 设置。")
        
    try:
        return json.loads(g_json), json.loads(s_cookies)
    except json.JSONDecodeError as e:
        print("JSON 解析失败，请检查 Secret 内容是否完整且格式正确。")
        raise e
        
def start_cloud_scraper():
    print(">>> 启动云端爬虫流程...")
    g_creds, s_cookies = get_env_config()

    # 1. 连接 Google Sheets
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(g_creds, scope)
    client = gspread.authorize(creds)
    sheet = client.open("Schoology_Data").sheet1
    existing_set = set(sheet.col_values(2))

    # 2. 配置无头浏览器 (云端必须无头)
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 3. 注入 Cookie 绕过登录
        # 必须先访问一次域名，才能注入 Cookie
        driver.get("https://queenscanada.schoology.com")
        time.sleep(2)
        
        for cookie in s_cookies:
            # 移除 Selenium 不支持的字段
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try:
                driver.add_cookie(cookie)
            except:
                pass
        
        # 4. 访问通知页
        driver.get("https://queenscanada.schoology.com/home/notifications")
        time.sleep(5)

        # 验证是否成功登录 (检查是否有内容)
        if "login" in driver.current_url.lower():
            print("ERROR: Cookie 已失效，请更新 GitHub Secrets！")
            return

        # 5. 抓取逻辑 (与之前相同)
        elements = driver.find_elements(By.XPATH, "//div[contains(@class, 's-edge-feed')]//div[contains(@class, 'feed-body')]")
        new_rows = []
        keywords = ["submitted", "resubmitted", "submission"]

        for elem in elements:
            text = elem.text.strip().replace("\n", " ")
            if any(k in text.lower() for k in keywords) and (text not in existing_set):
                # 抓链接
                url = ""
                try:
                    url = elem.find_element(By.TAG_NAME, "a").get_attribute("href")
                except: pass
                
                new_rows.append([time.strftime("%Y-%m-%d %H:%M:%S"), text, url])

        if new_rows:
            sheet.append_rows(new_rows)
            print(f">>> 成功抓取 {len(new_rows)} 条数据！")
        else:
            print(">>> 没有新通知。")

    finally:
        driver.quit()

if __name__ == "__main__":
    start_cloud_scraper()
