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
    抓取课程名称，并自动转换为简称 (如 SPH3U)
    """
    # ================= 课程映射表 (在这里添加你的规则) =================
    # 格式： "Schoology上的关键词": "飞书里的简称"
    # 注意：关键词写小写即可，脚本会自动忽略大小写
    COURSE_MAPPING = {
        "grade 11 physics": "SPH3U",
        "grade 12 physics": "SPH4U",
        "Grade 12 Advanced Functions": "MHF4U",   # 示例：你可以继续添加
        "Grade 12 Data Management": "MDM4U",   # 示例
        "calculus": "MCV4U"         # 示例
    }
    # ===============================================================

    try:
        print(f"   -> 正在打开作业页面...")
        driver.get(url)
        
        # 1. 抓取原始名称
        try:
            course_element = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/course/')]"))
            )
            raw_name = course_element.text.strip() # 例如: "Grade 11 Physics: Section 2526S3N"
            print(f"   -> 抓取到原始名称: {raw_name}")
            
            # 2. 【核心】执行映射转换
            lower_raw_name = raw_name.lower()
            
            for key, code in COURSE_MAPPING.items():
                if key in lower_raw_name:
                    print(f"   -> 匹配成功! 转换为: {code}")
                    return code
            
            # 3. 如果没匹配到，就返回原始名称 (方便你发现后去更新字典)
            print(f"   -> ⚠️ 未匹配到简称，保留原名。请更新 COURSE_MAPPING 字典。")
            return raw_name

        except Exception as e:
            print(f"   -> 未找到课程链接: {e}")
            return None

    except Exception as e:
        print(f"   -> 页面访问失败: {e}")
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
