"""
fix_roster_names.py
把飞书花名册里 "Last, First" 格式的姓名批量改为 "First Last"。

用法：
  FEISHU_APP_ID=... FEISHU_APP_SECRET=... FEISHU_APP_TOKEN=... \
  FEISHU_ROSTER_TABLE_ID=... python fix_roster_names.py

加 --dry-run 只打印预览，不写入飞书。
"""

import os
import sys
import re
import time
import requests


def get_token(app_id, app_secret):
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    ).json()
    if r.get("code") != 0:
        raise RuntimeError(f"Token 获取失败: {r}")
    return r["tenant_access_token"]


def fetch_all(token, app_token, table_id):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records, page_token = [], None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(url, headers=headers, params=params).json()
        if r.get("code") != 0:
            raise RuntimeError(f"拉取失败: {r}")
        data = r["data"]
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data["page_token"]
    return records


def reformat(name: str) -> str:
    """
    "Yu, Zhuoran"  → "Zhuoran Yu"
    "Smith, John A." → "John A. Smith"
    已经是正常格式的名字原样返回。
    """
    m = re.match(r'^([^,]+),\s*(.+)$', name.strip())
    if m:
        last, first = m.group(1).strip(), m.group(2).strip()
        return f"{first} {last}"
    return name  # 没有逗号，不动


def main():
    dry_run = "--dry-run" in sys.argv

    app_id     = os.environ["FEISHU_APP_ID"]
    app_secret = os.environ["FEISHU_APP_SECRET"]
    app_token  = os.environ["FEISHU_APP_TOKEN"]
    table_id   = os.environ["FEISHU_ROSTER_TABLE_ID"]

    token = get_token(app_id, app_secret)
    records = fetch_all(token, app_token, table_id)
    print(f"共 {len(records)} 条花名册记录")

    to_update = []
    for rec in records:
        record_id = rec["record_id"]
        fields = rec.get("fields", {})
        name_raw = str(fields.get("学生姓名", "")).strip()
        name_new = reformat(name_raw)
        if name_new != name_raw:
            print(f"  {name_raw!r:30s}  →  {name_new!r}")
            to_update.append((record_id, name_new))

    if not to_update:
        print("没有需要改名的记录。")
        return

    print(f"\n需要修改 {len(to_update)} 条记录。")
    if dry_run:
        print("（--dry-run 模式，未写入飞书）")
        return

    confirm = input("确认写入飞书？(y/N) ").strip().lower()
    if confirm != "y":
        print("已取消。")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    ok, fail = 0, 0
    for record_id, name_new in to_update:
        r = requests.put(f"{base}/{record_id}",
                         json={"fields": {"学生姓名": name_new}},
                         headers=headers).json()
        if r.get("code") == 0:
            ok += 1
        else:
            print(f"  ✗ 更新失败 {record_id}: {r}")
            fail += 1
        time.sleep(0.15)

    print(f"\n完成：成功 {ok} 条，失败 {fail} 条。")


if __name__ == "__main__":
    main()
