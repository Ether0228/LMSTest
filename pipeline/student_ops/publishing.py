"""Static HTML preview and Chromium PDF rendering for confirmed local snapshots."""
from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path
from typing import Any


class PDFRenderError(RuntimeError):
    pass


def find_chromium() -> str | None:
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if path := shutil.which(name):
            return path
    mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(mac) if mac.exists() else None


def render_pdf(html_path: Path, pdf_path: Path, binary: str | None = None) -> None:
    chrome = binary or find_chromium()
    if not chrome:
        raise PDFRenderError("chromium_not_available")
    try:
        subprocess.run([
            chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri(),
        ], check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise PDFRenderError("pdf_render_failed") from None
    if not pdf_path.exists() or not pdf_path.read_bytes().startswith(b"%PDF-"):
        raise PDFRenderError("pdf_render_failed")


def _section(title: str, content: str) -> str:
    return f"<section><h2>{html.escape(title)}</h2><p>{html.escape(content)}</p></section>"


def render_weekly_html(payload: dict[str, Any], drafts: dict[str, Any]) -> str:
    course = payload.get("course_weekly", {}).get("records", [])
    course_text = course[0].get("本周内容AI候选", "课程实际内容暂缺或待确认。") if course else "课程实际内容暂缺或待确认。"
    participation = payload.get("participation_candidates", [])
    interaction = "；".join(x["payload"].get("客观事实", "") for x in participation) or "本周没有可确认并可对外使用的互动证据。"
    attendance = payload.get("attendance", {})
    task = payload.get("tasks", {})
    grades = payload.get("grades", {})
    ielts = payload.get("ielts", {})
    pbl = payload.get("pbl", {})
    body = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>学生周反馈</title>",
        "<style>@page{size:A4;margin:16mm}body{font-family:'Noto Sans CJK SC','Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif;max-width:860px;margin:32px auto;color:#172033;line-height:1.65}header{border-bottom:3px solid #2f6fed}section{padding:12px 0;border-bottom:1px solid #dce3ef;break-inside:avoid}h1,h2{margin-bottom:6px}small{color:#5e6b82}.notice{background:#fff7e6;padding:10px}@media print{body{margin:0;max-width:none}}</style></head><body>",
        f"<header><h1>{html.escape(payload.get('student', {}).get('name', '学生'))}｜第{html.escape(str(payload.get('week', {}).get('number', '')))}周学习反馈</h1><small>状态：待智育师审核；本页为本地预览快照。</small></header>",
        _section("出勤观察", f"应参加 {attendance.get('应参加场次', '—')} 场；观察到参与 {attendance.get('观察到参与场次', '—')} 场。{attendance.get('状态', '')}"),
        _section("课程内容与互动", f"课程内容：{course_text}\n互动证据：{interaction}"),
        _section("任务与Backlog", f"任务总数 {task.get('总数', '—')}；积压 {task.get('backlog', '—')}。{drafts.get('任务执行AI草稿', '该模块暂不可生成草稿。')}"),
        _section("成绩", drafts.get("成绩总结AI草稿", "该模块暂不可生成草稿。") + f" 近期成绩记录数：{len(grades.get('近期作业分数', []))}。"),
        _section("IELTS", drafts.get("IELTS周总结AI草稿", "该模块暂不可生成草稿。") + f" 正式任务数：{len(ielts.get('正式任务', []))}。"),
        _section("PBL", drafts.get("PBL周总结AI草稿", "该模块暂不可生成草稿。") + f" 证据数：{len(pbl.get('evidence_manifest', []))}。"),
        _section("总体与下周支持", drafts.get("本周总体AI草稿", "部分模块缺失，需由智育师补充。")),
        "<p class='notice'>AI内容均为候选；考勤性质、任务质量、教育策略和最终发布均须人工确认。</p></body></html>",
    ]
    return "".join(body)
