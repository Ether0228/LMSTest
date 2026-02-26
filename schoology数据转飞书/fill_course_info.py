import os
import json
import time
import requests
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区域 =================
LOGIN_URL = "https://queenscanada.schoology.com"
# ===========================================

def get_env_config():
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    # 注意：这里我们只需要操作【作业库】
    lib_table_id = os.environ.get("FEISHU_LIB_TABLE_ID", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")
    
    if not all([app_id, app_secret, app_token, lib_table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
    return app_id, app_secret, app_token, lib_table_id, json.loads(s_cookies)

def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    return resp.json().get("tenant_access_token")

# === 1. 获取所有“所属课程”为空的记录 ===
def get_empty_course_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    
    # 筛选条件：所属课程 为空 (根据飞书API，空值筛选比较复杂，我们简单点：拉全部回来在代码里筛)
    # 如果数据量巨大，建议加 filter 参数
    records_to_process = []
    page_token = None
    
    print(">>> 正在查找未分类的作业...")
    while True:
        params = {"page_size": 500}
        if page_token: params["page_token"] = page_token
        
        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0: break
        
        for item in resp.get("data", {}).get("items", []):
            fields = item.get("fields", {})
            record_id = item.get("record_id")
            
            # 假设列名叫 "所属课程" 和 "作业链接"
            # 检查课程是否为空
            course = fields.get("所属课程")
            link_obj = fields.get("作业链接") # 可能是文本，也可能是超链接对象
            
            # 提取链接字符串
            link_str = ""
            if isinstance(link_obj, dict): link_str = link_obj.get("link", "")
            elif isinstance(link_obj, str): link_str = link_obj
            
            # 如果课程为空 且 有链接，加入待处理列表
            if not course and link_str and "schoology" in link_str:
                records_to_process.append({"id": record_id, "url": link_str})
                
        if not resp.get("data", {}).get("has_more"): break
        page_token = resp.get("data", {}).get("page_token")
        
    return records_to_process

# === 2. 更新飞书记录 ===
def update_feishu_record(token, app_token, table_id, record_id, course_name):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    
    payload = {
        "fields": {
            "所属课程": course_name
        }
    }
    requests.put(url, json=payload, headers=headers)
    print(f"   -> 已更新飞书: {course_name}")

# === 3. 核心：去网页抓取课程名 ===
def scrape_course_name(driver, url):
    """
    抓取课程名称 (兼容普通作业版和新版 Quiz/Assessment 版)
    """
    # 1. 映射表 (已更新)
    COURSE_MAPPING = {
        "grade 11 physics": "SPH3U",
        "grade 12 physics": "SPH4U",
        "grade 12 data management": "MDM4U",
        "grade 12 advanced functions": "MHF4U",
        "grade 11 functions": "MCR3U",
        "grade 12 calculus & vectors": "MCV4U",
        "grade 12 canadian and world issues": "CGW4U",
        "grade 12 english": "ENG4U",
        "grade 11 english": "ENG3U",
        "grade 12 nutrition & health": "HFA4U",
        "grade 12 visual arts" : "AVI4M",
        "g10 canadian history since wwi" : "CHC2D",
        "esl level 5": "ESLEO",
        "esl level 4": "ESLDO",
        "esl level 3": "ESLCO",
        "esl level 2": "ESLBO",
    }

    try:
        print(f"   -> 正在打开页面...")
        driver.get(url)
        
        # 给 React 页面一点渲染时间
        time.sleep(5)
        
        raw_name = ""

        # === 策略 A: 针对 Quiz/Assessment 的新版 Breadcrumb (根据你提供的HTML) ===
        try:
            # 逻辑：在 aria-label 为 Breadcrumb 的导航栏里，找第二个列表项 li 的 a 标签
            # 结构：Home(li1) > Course Name(li2) > ...
            breadcrumb_element = driver.find_element(By.XPATH, "//nav[@aria-label='Breadcrumb']//ol/li[2]//a")
            raw_name = breadcrumb_element.text.strip()
            if raw_name:
                print(f"   -> [Quiz策略] 抓取到: {raw_name}")
        except:
            pass

        # === 策略 B: 针对普通作业的旧版 Breadcrumb (span.course-title) ===
        if not raw_name:
            try:
                course_element = driver.find_element(By.CSS_SELECTOR, "span.course-title a")
                raw_name = course_element.text.strip()
                if raw_name:
                    print(f"   -> [普通作业策略] 抓取到: {raw_name}")
            except:
                pass

        # === 策略 C: 最终备用 - 网页标题 (Title) ===
        if not raw_name:
            page_title = driver.title
            if "|" in page_title:
                # Schoology Title: "Quiz Name | Course Name | Schoology"
                parts = page_title.split("|")
                raw_name = parts[-2].strip()
                print(f"   -> [Title策略] 抓取到: {raw_name}")

        # === 执行映射转换 ===
        if not raw_name:
            print("   -> ❌ 无法定位课程名")
            return None

        lower_name = raw_name.lower()
        for key, code in COURSE_MAPPING.items():
            if key in lower_name:
                print(f"   -> 🎯 匹配成功! ({raw_name} -> {code})")
                return code
        
        print(f"   -> ⚠️ 未匹配简称，返回原名: {raw_name}")
        return raw_name

    except Exception as e:
        print(f"   -> 运行出错: {e}")
        return None
def start_course_filler():
    print(">>> 启动作业分类补全脚本...")
    try:
        app_id, app_secret, app_token, lib_table_id, s_cookies = get_env_config()
        token = get_feishu_token(app_id, app_secret)
        
        # 1. 获取任务列表
        tasks = get_empty_course_records(token, app_token, lib_table_id)
        print(f">>> 发现 {len(tasks)} 个作业缺少课程信息")
        
        if not tasks:
            print(">>> 没有需要处理的任务，退出。")
            return

        # 2. 启动浏览器
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

        # 3. 登录
        driver.get(LOGIN_URL)
        time.sleep(3)
        for cookie in s_cookies:
            if 'sameSite' in cookie: del cookie['sameSite']
            if 'storeId' in cookie: del cookie['storeId']
            try: driver.add_cookie(cookie)
            except: pass
        
        # 4. 循环处理
        for i, task in enumerate(tasks):
            print(f"[{i+1}/{len(tasks)}] 处理: {task['url']}")
            
            course_name = scrape_course_name(driver, task['url'])
            
            if course_name:
                print(f"   识别到课程: {course_name}")
                update_feishu_record(token, app_token, lib_table_id, task['id'], course_name)
            else:
                print("   无法识别课程名称")
            
            # 稍微停顿，防止请求太快
            time.sleep(2)

    except Exception as e:
        print(f"运行出错: {e}")
    finally:
        if 'driver' in locals(): driver.quit()

if __name__ == "__main__":
    start_course_filler()
