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

# 内置课程名映射（兜底用，优先从飞书系统配置表读取）
DEFAULT_COURSE_MAPPING = {
    "grade 11 physics": "SPH3U",
    "grade 12 physics": "SPH4U",
    "grade 11 chemistry": "SCH3U",
    "grade 12 chemistry": "SCH4U",
    "grade 11 computer science": "ICS3U",
    "grade 12 data management": "MDM4U",
    "grade 12 advanced functions": "MHF4U",
    "grade 11 functions": "MCR3U",
    "grade 12 calculus & vectors": "MCV4U",
    "grade 12 english": "ENG4U",
    "grade 11 english": "ENG3U",
    "grade 11 food and culture": "HFC3M",
    "grade 12 nutrition & health": "HFA4U",
    "grade 11 visual arts": "AVI3M",
    "grade 12 visual arts": "AVI4M",
    "grade 12 fashion": "HNB4M",
    "g10 canadian history since wwi": "CHC2D",
    "grade 12 canadian and world issues": "CGW4U",
    "grade 12 business leadership": "BOH4M",
    "g12 analysing current economic issues": "CIA4U",
    "esl level 5": "ESLEO",
    "esl level 4": "ESLDO",
    "esl level 3": "ESLCO",
    "esl level 2": "ESLBO"
}

def get_env_config():
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    app_token = os.environ.get("FEISHU_APP_TOKEN", "").strip()
    # 注意：这里我们只需要操作【作业库】
    lib_table_id = os.environ.get("FEISHU_LIB_TABLE_ID", "").strip()
    config_table_id = os.environ.get("FEISHU_CONFIG_TABLE_ID", "").strip()
    s_cookies = os.environ.get("SCHOOLOGY_COOKIES")

    if not all([app_id, app_secret, app_token, lib_table_id, s_cookies]):
        raise ValueError("GitHub Secrets 配置不完整")
    return app_id, app_secret, app_token, lib_table_id, config_table_id, json.loads(s_cookies)

def get_feishu_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    return resp.json().get("tenant_access_token")


def fetch_course_mapping(token, app_token, config_table_id):
    """从飞书系统配置表读取 course_mapping，失败时返回 None（调用方使用 DEFAULT_COURSE_MAPPING）。"""
    if not config_table_id:
        return None
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{config_table_id}"
    headers = {"Authorization": f"Bearer {token}"}
    # 全量拉取后在 Python 端匹配，避免飞书文本 filter 不稳定
    all_items = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{base}/records", params=params, headers=headers).json()
        all_items.extend(r.get("data", {}).get("items", []))
        if not r.get("data", {}).get("has_more"):
            break
        page_token = r["data"]["page_token"]
    for item in all_items:
        if str(item["fields"].get("配置键", "")).strip() == "course_mapping":
            raw = item["fields"].get("配置值", "")
            text = raw if isinstance(raw, str) else (raw[0].get("text", "") if raw else "")
            try:
                return json.loads(text)
            except Exception:
                return None
    return None


def parse_semester_from_section_id(text):
    """从课程标题中提取学期标签。
    如 "ESL Level 5: Section 2526S4N"       → "2025-S4"
       "Grade 12 Data Management: Section 2526S3N" → "2025-S3"
    解析规则：2526S3N → start=2025, end=2026, sem=S3 → "2025-S3"（取开始学年）
    """
    m = re.search(r'[Ss]ection\s+(\d{2})(\d{2})(S\d+)N', text, re.IGNORECASE)
    if m:
        start_year = "20" + m.group(1)  # "25" → "2025"
        sem = m.group(3).upper()        # "S3"
        return f"{start_year}-{sem}"    # "2025-S3"
    return ""

# === 1. 获取所有"所属课程"为空的记录 ===
def get_empty_course_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}

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

            course = fields.get("所属课程")
            link_obj = fields.get("作业链接")

            # 提取链接字符串
            link_str = ""
            if isinstance(link_obj, dict): link_str = link_obj.get("link", "")
            elif isinstance(link_obj, str): link_str = link_obj

            # 仅处理课程为空且有 Schoology 链接的记录
            if not course and link_str and "schoology" in link_str:
                records_to_process.append({"id": record_id, "url": link_str})

        if not resp.get("data", {}).get("has_more"): break
        page_token = resp.get("data", {}).get("page_token")

    print(f">>> 共 {len(records_to_process)} 条待补全")
    return records_to_process

# === 2. 更新飞书记录 ===
def update_feishu_record(token, app_token, table_id, record_id, course_name, semester=""):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    fields = {"所属课程": course_name}
    if semester:
        fields["学期"] = semester

    resp = requests.put(url, json={"fields": fields}, headers=headers)
    rj = resp.json()
    semester_tag = f" | 学期={semester}" if semester else ""
    if rj.get("code") == 0:
        print(f"   -> 已更新飞书: {course_name}{semester_tag}")
    else:
        print(f"   -> ✗ 飞书写入失败: {rj.get('msg', '')} | 详情: {rj}")

# === 3. 核心：去网页抓取课程名 ===
def scrape_course_name(driver, url, course_mapping):
    """
    抓取课程名称并解析学期，兼容普通作业和 Quiz/Assessment 页面。
    返回 (course_code, semester)，失败时返回 (None, "")。
    course_mapping: {课程全名小写: 课程代码} 映射表，由调用方传入。
    """
    try:
        print(f"   -> 正在打开页面...")
        driver.get(url)

        # 给 React 页面一点渲染时间
        time.sleep(5)

        raw_name = ""

        # === 策略 A: 针对 Quiz/Assessment 的新版 Breadcrumb ===
        try:
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

        if not raw_name:
            print("   -> 无法定位课程名")
            return None, ""

        # === 提取学期（来自 Section ID，如 "Section 2526S4N" → "2026-S4"） ===
        semester = parse_semester_from_section_id(raw_name)
        if semester:
            print(f"   -> 学期识别: {semester}")

        # === 课程名映射：取冒号前的部分做匹配，避免 "Section XXXX" 干扰 ===
        # "ESL Level 5: Section 2526S4N" → 匹配 "esl level 5"
        name_for_mapping = raw_name.split(":")[0].strip().lower()
        for key, code in course_mapping.items():
            if key in name_for_mapping:
                print(f"   -> 匹配成功: {raw_name} -> {code}")
                return code, semester

        print(f"   -> 未匹配简称，返回原名: {raw_name}")
        return raw_name.split(":")[0].strip(), semester

    except Exception as e:
        print(f"   -> 运行出错: {e}")
        return None, ""
def start_course_filler():
    print(">>> 启动作业分类补全脚本...")
    try:
        app_id, app_secret, app_token, lib_table_id, config_table_id, s_cookies = get_env_config()
        token = get_feishu_token(app_id, app_secret)

        # 读取课程名映射：飞书配置表优先，内置映射兜底
        course_mapping = dict(DEFAULT_COURSE_MAPPING)
        if config_table_id:
            try:
                feishu_mapping = fetch_course_mapping(token, app_token, config_table_id)
                if feishu_mapping:
                    course_mapping.update(feishu_mapping)
                    print(f">>> 课程名映射：内置 {len(DEFAULT_COURSE_MAPPING)} 条 + 飞书 {len(feishu_mapping)} 条覆盖")
                else:
                    print(f">>> 课程名映射：仅使用内置映射（{len(course_mapping)} 条）")
            except Exception as e:
                print(f">>> 飞书映射读取失败，使用内置映射: {e}")

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

            course_code, semester = scrape_course_name(driver, task['url'], course_mapping)

            if course_code:
                update_feishu_record(token, app_token, lib_table_id, task['id'], course_code, semester)
            else:
                print("   无法识别课程名称")

            time.sleep(2)

    except Exception as e:
        print(f"运行出错: {e}")
    finally:
        if 'driver' in locals(): driver.quit()

if __name__ == "__main__":
    start_course_filler()
