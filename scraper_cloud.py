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

# ================= 配置区域 =================
LOGIN_URL = "https://queenscanada.schoology.com"
NOTIFICATION_URL = "https://queenscanada.schoology.com/home/notifications"
# ===========================================

def get_env_config():
    g_json = os.environ.get("GDRIVE_JSON")
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    if not g_json or not s_cookies:
        raise ValueError("GitHub Secrets 缺失")
    return json.loads(g_json), json.loads(s_cookies)

def normalize_text(text):
    return " ".join(text.split()).strip()

def start_cloud_scraper():
    print(">>> 启动云端爬虫流程...")
    try:
        g_creds, s_cookies = get_env_config()
    except Exception as e:
        print(f"配置读取失败: {e}")
        return

    # 1. 连接 Google Sheets
    print(">>> [Step 1] 连接数据库...")
    try:
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(g_creds, scope)
        client = gspread.authorize(creds)
        sh = client.open("Schoology_Data")
        try:
            sheet = sh.worksheet("Submissions")
        except:
            sheet = sh.sheet1
        existing_set = {normalize_text(t) for t in sheet.col_values(2)}
        print(f">>> 数据库就绪，已有记录: {len(existing_set)}")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return

    # 2. 启动浏览器
    print(">>> [Step 2] 启动浏览器...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        # 3. 注入 Cookie
        print(">>> [Step 3] 注入凭证...")
        driver.get(LOGIN_URL)
        time.sleep(5)
        for cookie in s_cookies:
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try: driver.add_cookie(cookie)
            except: pass
        
        # 4. 访问通知页
        print(f">>> [Step 4] 访问通知页...")
        driver.get(NOTIFICATION_URL)
        time.sleep(10) # 强行等待10秒，确保加载

        # 无论状态如何，先截个图备查
        driver.save_screenshot("debug_view.png")
        print(f"DEBUG: 页面标题: {driver.title} | 最终URL: {driver.current_url}")

        if "login" in driver.current_url.lower():
            print("!!! 错误: 发现跳转回登录页，Cookie 可能失效")
            return

        # 5. 加载更多 (尝试点击那个 li.notif-more a)
        for i in range(2):
            try:
                # 使用比较宽泛的寻找方式
                more_btns = driver.find_elements(By.CSS_SELECTOR, "li.notif-more a")
                if more_btns:
                    print(f">>> 点击更多 (第 {i+1} 次)...")
                    driver.execute_script("arguments[0].click();", more_btns[0])
                    time.sleep(5)
                else:
                    break
            except:
                break

        # 6. 抓取逻辑 (不依赖特定类名，抓取页面所有文本块)
        print(">>> [Step 6] 扫描内容...")
        # 尝试抓取所有可能是通知条目的元素
        potential_items = driver.find_elements(By.XPATH, "//div[contains(@class, 'feed')] | //li[contains(@class, 'item')]")
        
        # 如果还是抓不到，直接抓所有的 li
        if len(potential_items) < 5:
            potential_items = driver.find_elements(By.TAG_NAME, "li")

        print(f">>> 找到潜在条目数: {len(potential_items)}")
        
        new_rows = []
        keywords = ["submitted", "resubmitted", "submission"]

        for item in potential_items:
            try:
                raw_text = item.text
                if not raw_text: continue
                
                norm_text = normalize_text(raw_text)
                
                # 匹配逻辑
                if any(kw in norm_text.lower() for kw in keywords):
                    if norm_text not in existing_set:
                        # 找链接
                        link = ""
                        try:
                            link = item.find_element(By.TAG_NAME, "a").get_attribute("href")
                        except: pass
                        
                        print(f"发现新数据: {norm_text[:40]}...")
                        new_rows.append([time.strftime("%Y-%m-%d %H:%M:%S"), raw_text.replace("\n", " "), link])
                        existing_set.add(norm_text)
            except:
                continue

        # 7. 写入
        if new_rows:
            print(f">>> 写入 {len(new_rows)} 条数据...")
            sheet.append_rows(new_rows)
            print(">>> 完成！")
        else:
            print(">>> 未发现新通知。")

    except Exception as e:
        print(f"运行异常: {e}")
        driver.save_screenshot("debug_view.png") # 出错再截一张
    finally:
        driver.quit()

if __name__ == "__main__":
    from selenium.webdriver.common.by import By
    start_cloud_scraper()
