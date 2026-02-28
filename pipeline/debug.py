"""
debug.py — 飞书数据诊断工具

用法:
  python debug.py student <姓名>     # 查看某学生的汇总数据（成绩/缺交/关注）
  python debug.py gradebook <姓名>   # 查看 gradebook 爬取表里该学生的记录
  python debug.py list               # 列出所有学生及成绩覆盖情况
  python debug.py courses            # 列出 gradebook 里的课程名，帮助排查名字不匹配

凭证读取优先级:
  1. pipeline/.env 文件（本地调试用，格式同 CI Secret）
  2. 环境变量
"""

import os, sys, json, re, requests
from pathlib import Path


# ──────────────────────────────────────────────
# 凭证 & Token
# ──────────────────────────────────────────────

def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            idx = line.index("=") if "=" in line else -1
            if idx <= 0: continue
            k, v = line[:idx].strip(), line[idx+1:].strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v

def get_cfg():
    load_env()
    keys = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
            "FEISHU_SUMMARY_TABLE_ID", "FEISHU_GRADEBOOK_TABLE_ID"]
    cfg = {k: os.environ.get(k, "").strip() for k in keys}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print(f"❌ 缺少环境变量: {', '.join(missing)}")
        print("   请在 pipeline/.env 里配置（参考 CI Secrets）")
        sys.exit(1)
    return cfg

def get_token(cfg):
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": cfg["FEISHU_APP_ID"], "app_secret": cfg["FEISHU_APP_SECRET"]}
    ).json()
    tok = r.get("tenant_access_token")
    if not tok:
        print("❌ 获取 token 失败:", r)
        sys.exit(1)
    return tok

def feishu_get(tok, app_token, table_id, params=""):
    headers = {"Authorization": f"Bearer {tok}"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    items, page_token = [], None
    while True:
        qs = f"page_size=100{('&page_token=' + page_token) if page_token else ''}"
        if params: qs += "&" + params
        r = requests.get(f"{url}?{qs}", headers=headers).json()
        items.extend(r.get("data", {}).get("items", []))
        if r.get("data", {}).get("has_more"):
            page_token = r["data"]["page_token"]
        else:
            break
    return items

def feishu_filter(tok, app_token, table_id, field, op, value):
    f = json.dumps({"conjunction":"and","conditions":[{"field_name":field,"operator":op,"value":value}]})
    headers = {"Authorization": f"Bearer {tok}"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    r = requests.get(f"{url}?filter={requests.utils.quote(f)}&page_size=100", headers=headers).json()
    return r.get("data", {}).get("items", [])


# ──────────────────────────────────────────────
# 命令：student
# ──────────────────────────────────────────────

def cmd_student(name):
    cfg = get_cfg()
    tok = get_token(cfg)
    print(f"\n🔍 查询学生: {name}")

    # 全表搜（filter 对文本字段有时不稳定）
    all_rows = feishu_get(tok, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_SUMMARY_TABLE_ID"])
    row = next((r for r in all_rows
                if name.lower() in str(r["fields"].get("学生姓名", "")).lower()), None)

    if not row:
        names = [r["fields"].get("学生姓名","") for r in all_rows]
        print(f"❌ 汇总表里没有匹配 '{name}' 的学生")
        print(f"   共 {len(all_rows)} 名学生，前10: {names[:10]}")
        return

    f = row["fields"]
    name_actual = f.get("学生姓名", "")
    print(f"✅ 找到: {name_actual}  |  学年:{f.get('学年','')}  学期:{f.get('学期号','')}")
    print(f"   更新时间: {f.get('summaryUpdatedAt','')}")

    # 课程进度
    cp_raw = f.get("课程进度JSON", "")
    print(f"\n📚 课程进度JSON ({len(cp_raw)} chars):")
    if not cp_raw:
        print("   ❌ 字段为空")
    else:
        try:
            cp = json.loads(cp_raw)
            for c in cp:
                grade = f"{c['current_grade']}%" if c.get("current_grade") is not None else "❌ 无成绩"
                aol = len(c.get("aol_details") or [])
                print(f"   [{c['course']}]  完成:{c.get('completion',0)}%  成绩:{grade}  "
                      f"AoL详情:{aol}条  aolSubmitted:{c.get('aolSubmitted',0)}")
        except Exception as e:
            print(f"   parse error: {e}")
            print(f"   raw: {cp_raw[:200]}")

    # 关注列表
    at_raw = f.get("关注列表JSON", "")
    print(f"\n⚠️  关注列表JSON ({len(at_raw)} chars):")
    if at_raw:
        try:
            at = json.loads(at_raw)
            by_type = {}
            for i in at: by_type[i.get("type","?")] = by_type.get(i.get("type","?"),0)+1
            print(f"   类型分布: {by_type}")
        except Exception as e:
            print(f"   parse error: {e}")


# ──────────────────────────────────────────────
# 命令：gradebook
# ──────────────────────────────────────────────

def cmd_gradebook(name):
    cfg = get_cfg()
    tok = get_token(cfg)
    print(f"\n🔍 Gradebook 查询: {name}")

    all_rows = feishu_get(tok, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"])
    print(f"   Gradebook 总记录: {len(all_rows)}")

    matched = [r for r in all_rows
               if name.lower() in str(r["fields"].get("学生姓名","")).lower()]
    print(f"   匹配 '{name}' 的记录: {len(matched)} 条")

    if not matched:
        # 显示所有不重复的学生名帮助排查
        names = sorted(set(r["fields"].get("学生姓名","") for r in all_rows))
        print(f"   Gradebook 里的学生 ({len(names)} 人): {names}")
        return

    # 按课程分组显示
    by_course = {}
    for r in matched:
        c = r["fields"].get("课程名", "未知")
        by_course.setdefault(c, []).append(r["fields"])

    for course, rows in by_course.items():
        pct = rows[0].get("课程总分%")
        print(f"\n   [{course}]  课程总分%: {pct}  作业数: {len(rows)}")
        # 显示最近3条作业
        for r in rows[:3]:
            print(f"     - {r.get('作业名','')[:40]}  得分率:{r.get('得分率')}%")


# ──────────────────────────────────────────────
# 命令：list
# ──────────────────────────────────────────────

def cmd_list():
    cfg = get_cfg()
    tok = get_token(cfg)

    all_rows = feishu_get(tok, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_SUMMARY_TABLE_ID"])
    print(f"\n📋 汇总表共 {len(all_rows)} 名学生\n")
    print(f"{'姓名':<20} {'课程数':>5} {'有成绩':>6} {'缺交':>5} {'关注':>5}")
    print("-" * 50)

    for row in sorted(all_rows, key=lambda r: str(r["fields"].get("学生姓名",""))):
        f = row["fields"]
        name = str(f.get("学生姓名", ""))
        cp_raw = f.get("课程进度JSON", "")
        at_raw = f.get("关注列表JSON", "")
        try:
            cp = json.loads(cp_raw) if cp_raw else []
            graded = sum(1 for c in cp if c.get("current_grade") is not None)
            total_missing = sum(c.get("missingCount", 0) for c in cp)
        except: cp, graded, total_missing = [], 0, 0
        try:
            at = json.loads(at_raw) if at_raw else []
            low_score = sum(1 for i in at if i.get("type") == "low_score")
        except: low_score = 0

        grade_flag = "✅" if graded == len(cp) and len(cp) > 0 else ("⚠️" if graded > 0 else "❌")
        print(f"{name:<20} {len(cp):>5} {grade_flag}{graded:>4} {total_missing:>5} {low_score:>5}")


# ──────────────────────────────────────────────
# 命令：courses
# ──────────────────────────────────────────────

def cmd_courses():
    cfg = get_cfg()
    tok = get_token(cfg)

    gb_rows = feishu_get(tok, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_GRADEBOOK_TABLE_ID"])
    sm_rows = feishu_get(tok, cfg["FEISHU_APP_TOKEN"], cfg["FEISHU_SUMMARY_TABLE_ID"])

    gb_courses = sorted(set(r["fields"].get("课程名","") for r in gb_rows if r["fields"].get("课程名")))
    sm_courses = set()
    for r in sm_rows:
        try:
            cp = json.loads(r["fields"].get("课程进度JSON","") or "[]")
            sm_courses.update(c.get("course","") for c in cp)
        except: pass
    sm_courses = sorted(sm_courses)

    print(f"\n📊 Gradebook 表里的课程名 ({len(gb_courses)}):")
    for c in gb_courses: print(f"  {'✅' if c in sm_courses else '❌'} {c}")

    print(f"\n📊 汇总表里的课程名 ({len(sm_courses)}):")
    for c in sm_courses: print(f"  {'✅' if c in gb_courses else '⚠️(无成绩)'} {c}")

    unmatched_gb = [c for c in gb_courses if c not in sm_courses]
    unmatched_sm = [c for c in sm_courses if c not in gb_courses]
    if unmatched_gb: print(f"\n❌ Gradebook 有、汇总表无（名字不匹配）: {unmatched_gb}")
    if unmatched_sm: print(f"⚠️  汇总表有、Gradebook 无（未爬取）: {unmatched_sm}")


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def get_cfg_with_config_table():
    """get_cfg() 的扩展版，额外要求 FEISHU_CONFIG_TABLE_ID。"""
    cfg = get_cfg()
    load_env()
    config_table_id = os.environ.get("FEISHU_CONFIG_TABLE_ID", "").strip()
    if not config_table_id:
        print("❌ 缺少 FEISHU_CONFIG_TABLE_ID，请在 pipeline/.env 里配置")
        sys.exit(1)
    cfg["FEISHU_CONFIG_TABLE_ID"] = config_table_id
    return cfg


# ──────────────────────────────────────────────
# 命令：init-config
# ──────────────────────────────────────────────

DEFAULT_COURSE_MAPPING = {
    "grade 11 physics":               "SPH3U",
    "grade 12 physics":               "SPH4U",
    "grade 12 data management":       "MDM4U",
    "grade 12 advanced functions":    "MHF4U",
    "grade 11 functions":             "MCR3U",
    "grade 12 calculus & vectors":    "MCV4U",
    "grade 12 canadian and world issues": "CGW4U",
    "grade 12 english":               "ENG4U",
    "grade 11 english":               "ENG3U",
    "grade 12 nutrition & health":    "HFA4U",
    "grade 12 visual arts":           "AVI4M",
    "g10 canadian history since wwi": "CHC2D",
    "esl level 5":                    "ESLEO",
    "esl level 4":                    "ESLDO",
    "esl level 3":                    "ESLCO",
    "esl level 2":                    "ESLBO",
}

def _upsert_config(tok, app_token, table_id, key, value):
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    flt = json.dumps({"conjunction":"and","conditions":[{"field_name":"配置键","operator":"is","value":[key]}]})
    r = requests.get(f"{base}/records", params={"filter": flt, "page_size": 5}, headers=headers).json()
    items = r.get("data", {}).get("items", [])
    payload = {"fields": {"配置键": key, "配置值": value}}
    if items:
        record_id = items[0]["record_id"]
        requests.put(f"{base}/records/{record_id}", json=payload, headers=headers)
        return "updated"
    else:
        requests.post(f"{base}/records", json=payload, headers=headers)
        return "created"

def cmd_init_config():
    cfg = get_cfg_with_config_table()
    tok = get_token(cfg)
    app_token = cfg["FEISHU_APP_TOKEN"]
    table_id  = cfg["FEISHU_CONFIG_TABLE_ID"]

    print("\n📝 初始化飞书系统配置表...")

    # 写入 course_mapping
    mapping_json = json.dumps(DEFAULT_COURSE_MAPPING, ensure_ascii=False)
    action = _upsert_config(tok, app_token, table_id, "course_mapping", mapping_json)
    print(f"  course_mapping ({len(DEFAULT_COURSE_MAPPING)} 条) → {action}")

    # 检查 grading_period 是否已存在
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    headers = {"Authorization": f"Bearer {tok}"}
    flt = json.dumps({"conjunction":"and","conditions":[{"field_name":"配置键","operator":"is","value":["grading_period"]}]})
    r = requests.get(f"{base}/records", params={"filter": flt, "page_size": 5}, headers=headers).json()
    gp_items = r.get("data", {}).get("items", [])
    if gp_items:
        print(f"  grading_period → 已存在，跳过")
    else:
        print(f"  grading_period → 未找到（运行 pipeline 后会自动写入）")

    print("\n✅ 完成！以后在飞书"系统配置"表里直接修改 course_mapping 的配置值即可。")
    print("   下次 pipeline 运行时会自动读取最新映射。")


# ──────────────────────────────────────────────

HELP = """
用法:
  python debug.py student <姓名>     查看某学生的汇总数据
  python debug.py gradebook <姓名>   查看该学生在 gradebook 表里的记录
  python debug.py list               列出所有学生及成绩覆盖情况
  python debug.py courses            对比 gradebook 与汇总表的课程名，排查不匹配
  python debug.py init-config        把默认课程名映射写入飞书系统配置表（只需跑一次）
"""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(HELP)
    elif args[0] == "student" and len(args) >= 2:
        cmd_student(" ".join(args[1:]))
    elif args[0] == "gradebook" and len(args) >= 2:
        cmd_gradebook(" ".join(args[1:]))
    elif args[0] == "list":
        cmd_list()
    elif args[0] == "courses":
        cmd_courses()
    elif args[0] == "init-config":
        cmd_init_config()
    else:
        print(HELP)
