#!/usr/bin/env python3
"""Scan registered course groups for Docx intelligent-minute sources.

This is a read-only collection stage.  It produces a source ledger for review
and never writes a source to ``学期场次`` until the source maps to exactly one
scheduled session in a separate mapping step.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from student_ops.course_source_discovery import discover_smart_minutes


def cli_json(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(args, check=False, text=True, capture_output=True)
    if completed.returncode:
        try:
            error = json.loads(completed.stderr)
            message = error.get("error", {}).get("message", "lark_cli_failed")
        except json.JSONDecodeError:
            message = "lark_cli_failed"
        raise RuntimeError(message)
    response = json.loads(completed.stdout)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "lark_cli_failed"))
    return response


def list_group_messages(chat_id: str, start: str, end: str, identity: str, profile: str | None) -> list[dict[str, Any]]:
    command = [
        "lark-cli", "im", "+chat-messages-list", "--chat-id", chat_id,
        "--start", start, "--end", end, "--order", "asc", "--page-all",
        "--no-reactions", "--as", identity, "--format", "json",
    ]
    if profile:
        command += ["--profile", profile]
    response = cli_json(command)
    return list(response.get("data", {}).get("messages", []))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/course_group_registry.json"))
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--profile")
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    messages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for group in registry:
        if not group.get("启用", True):
            continue
        try:
            messages.extend(list_group_messages(group["chat_id"], args.start, args.end, args.identity, args.profile))
        except RuntimeError as error:
            errors.append({"chat_id": group["chat_id"], "课程编码": group["课程编码"], "错误": str(error)})
    ledger = discover_smart_minutes(messages, registry)
    output = {"范围": {"开始": args.start, "结束": args.end}, "来源记录": ledger, "扫描异常": errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"发现智能纪要": len(ledger), "扫描异常": len(errors), "输出": str(args.output)}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
