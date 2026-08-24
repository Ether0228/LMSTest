#!/usr/bin/env python3
"""Fetch discovered intelligent-minute documents into an auditable source cache.

No AI or Base mutation occurs here.  A failed read remains an explicit source
status so downstream course summaries cannot invent lesson content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def fetch_doc(doc: str, identity: str, profile: str | None) -> dict[str, Any]:
    command = ["lark-cli", "docs", "+fetch", "--doc", doc, "--doc-format", "markdown", "--as", identity, "--format", "json"]
    if profile:
        command += ["--profile", profile]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    raw = completed.stdout if completed.returncode == 0 else completed.stderr
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        return {"状态": "读取失败", "错误": "lark_cli_invalid_response"}
    if completed.returncode or not response.get("ok"):
        return {"状态": "读取失败", "错误": response.get("error", {}).get("message", "lark_cli_failed")}
    document = response.get("data", {}).get("document", {})
    content = str(document.get("content") or "")
    if not content.strip():
        return {"状态": "读取失败", "错误": "empty_document_content"}
    return {
        "状态": "已读取",
        "文档版本": document.get("revision_id"),
        "正文": content,
        "正文hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 means all discovered sources")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    discovered = json.loads(args.ledger.read_text(encoding="utf-8"))["来源记录"]
    if args.limit:
        discovered = discovered[:args.limit]
    records = []
    for row in discovered:
        record = dict(row)
        record.update(fetch_doc(str(row["智能纪要URL"]), args.identity, args.profile))
        records.append(record)
    output = {"来源记录": records, "统计": {"总数": len(records), "已读取": sum(r["状态"] == "已读取" for r in records), "读取失败": sum(r["状态"] == "读取失败" for r in records)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["统计"], ensure_ascii=False))
    return 0 if not output["统计"]["读取失败"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
