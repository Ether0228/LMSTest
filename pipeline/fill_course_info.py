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
    "esl level 2": "ESLBO",
    "g12 international business fundamentals": "BBB4M",
    "grade 12 simplified chinese": "LKBDU",
    "grade 11 biology": "SBI3U",
    "grade 10 science": "SNC2D",
    "grade 12 computer science": "ICS4U",
    "g12 ontario secondary school literacy":"OLC4O"
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
    解析规则：2526S3N → start=2025, end=2026, sem=S3 → "2025-S3"（取学年起始年）
    """
    m = re.search(r'[Ss]ection\s+(\d{2})(\d{2})(S\d+)N', text, re.IGNORECASE)
    if m:
        start_year = "20" + m.group(1)  # "25" → "2025"
        sem = m.group(3).upper()        # "S3"
        return f"{start_year}-{sem}"    # "2025-S3"
    return ""


def normalize_course_title(text):
    """标准化课程标题，仅保留课程名部分用于做精确映射。"""
    base = str(text or "").split(":")[0].strip().lower()
    return re.sub(r"\s+", " ", base)


def resolve_course_code(raw_name, course_mapping):
    """
    只对标准化后的课程标题做精确匹配，避免 ENG3U/ENG4U 这类近似课程误判。
    返回 (course_code, normalized_title)；失败时返回 (None, normalized_title)。
    """
    normalized_title = normalize_course_title(raw_name)
    if not normalized_title:
        return None, normalized_title
    return course_mapping.get(normalized_title), normalized_title

def is_blank_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


# === 1. 获取所有需要补全课程或学期的记录 ===
def get_incomplete_course_records(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}

    records_to_process = []
    page_token = None

    print(">>> 正在查找缺少课程或学期的作业...")
    while True:
        params = {"page_size": 500}
        if page_token: params["page_token"] = page_token

        resp = requests.get(url, headers=headers, params=params).json()
        if resp.get("code") != 0: break

        for item in resp.get("data", {}).get("items", []):
            fields = item.get("fields", {})
            record_id = item.get("record_id")

            course = fields.get("所属课程")
            semester = fields.get("学期")
            link_obj = fields.get("作业链接")

            # 提取链接字符串
            link_str = ""
            if isinstance(link_obj, dict): link_str = link_obj.get("link", "")
            elif isinstance(link_obj, str): link_str = link_obj

            needs_course = is_blank_value(course)
            needs_semester = is_blank_value(semester)

            # 处理课程为空或学期为空，且有 Schoology 链接的记录。
            if (needs_course or needs_semester) and link_str and "schoology" in link_str:
                records_to_process.append({
                    "id": record_id,
                    "url": link_str,
                    "needs_course": needs_course,
                    "needs_semester": needs_semester,
                    "existing_course": course,
                    "existing_semester": semester,
                })

        if not resp.get("data", {}).get("has_more"): break
        page_token = resp.get("data", {}).get("page_token")

    print(f">>> 共 {len(records_to_process)} 条待补全")
    return records_to_process

# === 2. 更新飞书记录 ===
def update_feishu_record(
    token, app_token, table_id, record_id,
    course_name=None, semester="", update_course=True, update_semester=True,
):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    fields = {}
    if update_course and course_name:
        fields["所属课程"] = course_name
    if update_semester and semester:
        fields["学期"] = semester

    if not fields:
        print("   -> 无可写入字段，跳过")
        return

    resp = requests.put(url, json={"fields": fields}, headers=headers)
    rj = resp.json()
    desc = " | ".join(f"{k}={v}" for k, v in fields.items())
    if rj.get("code") == 0:
        print(f"   -> 已更新飞书: {desc}")
    else:
        print(f"   -> ✗ 飞书写入失败: {rj.get('msg', '')} | 详情: {rj}")

# === 3. 核心：去网页抓取课程名 ===
def scrape_course_name(driver, url, course_mapping, nid_to_course=None):
    """
    抓取课程名称并解析学期，兼容普通作业和 Quiz/Assessment 页面。
    返回 (course_code, semester)，失败时返回 (None, "")。
    course_mapping: {课程全名小写: 课程代码} 映射表，由调用方传入。
    nid_to_course:  {section_nid: (course_code, semester)} 映射表（可选）。
    """
    try:
        print(f"   -> 正在打开页面...")
        driver.get(url)

        # 给 React 页面一点渲染时间
        time.sleep(5)

        final_url = driver.current_url
        nid_course_code = None
        nid_semester = ""

        # === 策略 A0: 从重定向后的 URL 提取 Section NID，先记下映射结果，稍后与页面标题交叉校验 ===
        if nid_to_course:
            m = re.search(r'/course/(\d+)/', final_url)
            if m:
                nid = m.group(1)
                if nid in nid_to_course:
                    nid_course_code, nid_semester = nid_to_course[nid]
                    print(f"   -> [策略A0-NID] {nid} → {nid_course_code} ({nid_semester})")

        raw_name = ""

        # === 策略 A: 针对 Quiz/Assessment 的新版 Breadcrumb ===
        try:
            breadcrumb_element = driver.find_element(By.XPATH, "//nav[@aria-label='Breadcrumb']//ol/li[2]//a")
            raw_name = breadcrumb_element.text.strip()
            if raw_name:
                print(f"   -> [Quiz策略A1] 抓取到: {raw_name}")
        except:
            pass

        # === 策略 A2: Quiz 页面 nav 无 aria-label，用 main 内第一个 nav 的 li[2] ===
        if not raw_name:
            try:
                breadcrumb_element = driver.find_element(By.XPATH, "//main//nav//ol/li[2]/a")
                raw_name = breadcrumb_element.text.strip()
                if raw_name:
                    print(f"   -> [Quiz策略A2] 抓取到: {raw_name}")
            except:
                pass

        # === 策略 A3: 直接找 href 以 /course/ 开头的链接（React 渲染页面通用）===
        if not raw_name:
            try:
                course_link = driver.find_element(By.XPATH, "//a[starts-with(@href, '/course/')]")
                raw_name = course_link.text.strip()
                if raw_name:
                    print(f"   -> [课程链接策略A3] 抓取到: {raw_name}")
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
            if nid_course_code:
                print(f"   -> 页面标题缺失，降级使用 NID 结果: {nid_course_code}")
                return nid_course_code, nid_semester
            return None, ""

        # === 提取学期（来自 Section ID，如 "Section 2526S4N" → "2025-S4"） ===
        title_semester = parse_semester_from_section_id(raw_name)
        if title_semester:
            print(f"   -> 学期识别: {title_semester}")

        title_course_code, normalized_title = resolve_course_code(raw_name, course_mapping)
        if title_course_code:
            print(f"   -> 标题映射成功: {normalized_title} -> {title_course_code}")

        if nid_course_code and title_course_code:
            if nid_course_code != title_course_code:
                print(
                    f"   -> [冲突] NID={nid_course_code} 但标题={title_course_code} "
                    f"(title={normalized_title}, url={final_url})，跳过写入"
                )
                return None, ""
            return title_course_code, title_semester or nid_semester

        if title_course_code:
            return title_course_code, title_semester or nid_semester

        if nid_course_code:
            print(f"   -> 标题未命中映射，降级使用 NID 结果: {nid_course_code}")
            return nid_course_code, nid_semester

        if title_semester:
            print(f"   -> 课程未匹配，但可补写学期: {title_semester}")
            return None, title_semester

        print(f"   -> 未匹配到课程简称，跳过 (raw={raw_name.split(':')[0].strip()[:40]})")
        return None, ""

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

        # 从 SCHOOLOGY_SECTION_NIDS 建立 NID → (course_code, semester) 映射（Strategy A0 用）
        nid_to_course = {}
        section_nids_raw = os.environ.get("SCHOOLOGY_SECTION_NIDS", "").strip()
        if section_nids_raw:
            try:
                sections_raw = json.loads(section_nids_raw)
                for nid, title in sections_raw.items():
                    course_raw = title.split(":")[0].strip().lower()
                    course_raw = re.sub(r'\s+', ' ', course_raw)
                    code = course_mapping.get(course_raw, title.split(":")[0].strip())
                    # 解析学期标签（如 2025-S4）
                    sm = re.search(r'(\d{2})(\d{2})(S\d)N', title)
                    sem = f"20{sm.group(1)}-{sm.group(3).upper()}" if sm else ""
                    nid_to_course[str(nid)] = (code, sem)
                print(f">>> NID→课程映射：{len(nid_to_course)} 个 section")
            except Exception as e:
                print(f">>> SCHOOLOGY_SECTION_NIDS 解析失败: {e}")

        # 1. 获取任务列表
        tasks = get_incomplete_course_records(token, app_token, lib_table_id)
        print(f">>> 发现 {len(tasks)} 个作业缺少课程或学期信息")

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

            course_code, semester = scrape_course_name(driver, task['url'], course_mapping, nid_to_course)

            if course_code or semester:
                update_feishu_record(
                    token, app_token, lib_table_id, task['id'],
                    course_name=course_code,
                    semester=semester,
                    update_course=task.get("needs_course", False),
                    update_semester=task.get("needs_semester", False),
                )
            else:
                print("   无法识别课程名称或学期")

            time.sleep(2)

    except Exception as e:
        print(f"运行出错: {e}")
    finally:
        if 'driver' in locals(): driver.quit()

if __name__ == "__main__":
    start_course_filler()
