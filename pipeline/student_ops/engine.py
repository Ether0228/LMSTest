"""Deterministic V1 workflow engine for the Student Learning Operations System.

The engine is intentionally fixture-first: it makes auditable artefacts, never
contacts Feishu/Schoology, and never turns an AI candidate into a formal fact.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

SIX_HEADINGS = ("本节主题", "学习内容", "课堂活动", "课堂任务与评价", "学习情况与问题", "后续安排")
WORKFLOWS = (
    "session_content", "course_weekly", "participation", "tasks", "grades",
    "ielts", "pbl", "weekly_payload", "weekly_drafts", "publish", "all",
)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_result(status: str, payload: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "payload": payload, "warnings": warnings or []}


def mock_session_minutes(session: dict[str, Any]) -> str:
    """A test-only adapter. Real AI is deliberately opt-in outside CI."""
    return str(session.get("mock_ai_response") or "")


def parse_six_sections(text: str) -> tuple[dict[str, str] | None, list[str]]:
    sections: dict[str, str] = {}
    positions: list[tuple[int, str]] = []
    for heading in SIX_HEADINGS:
        marker = f"【{heading}】"
        pos = text.find(marker)
        if pos < 0:
            return None, [f"缺少标题：{heading}"]
        positions.append((pos, heading))
    if positions != sorted(positions):
        return None, ["六段标题顺序不正确"]
    for index, (pos, heading) in enumerate(positions):
        start = pos + len(heading) + 2
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        content = text[start:end].strip()
        if not content:
            return None, [f"空段落：{heading}"]
        sections[heading] = content
    return sections, []


def validate_session_minutes(text: str, sections: dict[str, str] | None) -> list[str]:
    errors: list[str] = []
    if not sections:
        return ["无法解析六段式内容"]
    content_lines = [line.strip("-• ") for line in sections["学习内容"].splitlines() if line.strip()]
    if not 2 <= len(content_lines) <= 6:
        errors.append("学习内容必须为2—6条")
    if not 80 <= len(text.replace("\n", "")) <= 800:
        errors.append("候选纪要长度不在V1容许范围")
    prohibited = ("态度不端正", "性格", "天赋", "懒惰", "收获颇丰", "气氛良好", "显著提升")
    if any(word in text for word in prohibited):
        errors.append("包含禁止的人格化或宣传性表达")
    if "Test（随堂小测）" in text or "Quiz（阶段测试）" in text:
        errors.append("Quiz/Test术语使用错误")
    return errors


def session_content(data: dict[str, Any]) -> dict[str, Any]:
    results = []
    for session in data.get("sessions", []):
        source = str(session.get("source_text") or "").strip()
        base = {"session_id": session.get("session_id"), "schema_version": "session_course_minutes_v1"}
        if not source:
            results.append(make_result("missing_source", base, ["缺少已确认的纪要来源；未调用AI"]))
            continue
        candidate = mock_session_minutes(session)
        sections, parse_errors = parse_six_sections(candidate)
        errors = parse_errors + validate_session_minutes(candidate, sections)
        if errors:
            results.append(make_result("invalid_schema", {**base, "candidate": candidate}, errors))
            continue
        # This remains an AI candidate even when the fixture says it was reviewed.
        results.append(make_result("success", {
            **base, "candidate": candidate, "structured": sections,
            "input_hash": stable_hash(source),
            "confirmation_status": session.get("confirmation_status", "待确认"),
        }))
    overall = "success" if results and all(x["status"] == "success" for x in results) else "partial"
    return make_result(overall, {"records": results})


def course_weekly(data: dict[str, Any], sessions_result: dict[str, Any]) -> dict[str, Any]:
    confirmed = []
    for row in sessions_result["payload"]["records"]:
        if row["status"] == "success" and row["payload"].get("confirmation_status") == "已确认":
            confirmed.append(row["payload"])
    if not confirmed:
        return make_result("blocked", {"records": []}, ["没有已确认的实际课程内容，不能以计划内容替代"])
    content = [r["structured"]["学习内容"] for r in confirmed]
    record = {
        "课程周唯一键": f"{data['course']['course_offering_id']}:{data['week']['number']}:全班",
        "课程开设": data["course"]["course_offering_id"], "教学周": data["week"]["number"],
        "本周内容AI候选": "\n".join(content), "来源场次": [r["session_id"] for r in confirmed],
        "确认状态": "待课程责任老师确认", "事实截止时间": data["week"]["end"],
    }
    return make_result("success", {"records": [record]})


def participation(data: dict[str, Any]) -> dict[str, Any]:
    roster = set(data.get("student", {}).get("aliases", [])) | {data.get("student", {}).get("name", "")}
    records = []
    for event in data.get("participation_events", []):
        speaker = event.get("speaker")
        if speaker not in roster:
            records.append(make_result("unmatched", {"session_id": event.get("session_id"), "speaker": speaker}, ["无法唯一匹配学生；不进入对外稿"]))
            continue
        records.append(make_result("candidate", {
            "session_id": event.get("session_id"), "student_id": data["student"]["id"],
            "类别": event.get("category"), "方向": event.get("direction"),
            "客观事实": event.get("evidence"), "证据来源": event.get("source"),
            "确认状态": "待确认",
        }))
    return make_result("success", {"records": records})


def effective_deadline(task: dict[str, Any]) -> str | None:
    return task.get("返工Deadline") or task.get("补做Deadline") or task.get("原始Deadline")


def tasks(data: dict[str, Any]) -> dict[str, Any]:
    today = date.fromisoformat(data["week"]["end"])
    records = []
    for task in data.get("tasks", []):
        record = copy.deepcopy(task)
        deadline = effective_deadline(task)
        record["当前有效Deadline"] = deadline
        submitted = task.get("当前提交状态") in ("已提交", "已重交")
        passed = task.get("检查状态") == "已通过"
        overdue = bool(deadline and date.fromisoformat(deadline) < today and not passed)
        record["Backlog状态"] = "积压" if overdue else "非积压"
        record["积压天数"] = max((today - date.fromisoformat(deadline)).days, 0) if overdue else 0
        record["当前任务状态"] = "已通过" if passed else ("已提交待检查" if submitted else "未提交")
        records.append(record)
    return make_result("success", {"records": records, "backlog_count": sum(x["Backlog状态"] == "积压" for x in records)})


def grades(data: dict[str, Any]) -> dict[str, Any]:
    current = data.get("grades", [])
    old = {x["grade_id"]: x for x in data.get("prior_grades", [])}
    events = []
    for grade in current:
        previous = old.get(grade["grade_id"])
        if not previous:
            kind = "首次评分"
        elif previous.get("score") != grade.get("score"):
            kind = "改分"
        elif previous.get("comment") != grade.get("comment"):
            kind = "评语变化"
        else:
            continue
        events.append({"event_id": stable_hash([kind, grade, previous])[:20], "类型": kind, "grade_id": grade["grade_id"], "前值": previous, "后值": grade})
    # event ids are stable, so reruns neither overwrite nor create duplicates downstream.
    observations = data.get("course_grade_observations", [])
    trend = "无课程总分观察历史"
    if len(observations) >= 2:
        trend = {"周初": observations[0]["overall"], "周末": observations[-1]["overall"]}
    return make_result("success", {"append_only_events": events, "近期作业分数": current, "课程总分": trend})


def ielts(data: dict[str, Any], task_result: dict[str, Any]) -> dict[str, Any]:
    ielts_tasks = [x for x in task_result["payload"]["records"] if x.get("所属模块") == "IELTS"]
    candidates = []
    if data.get("student", {}).get("IELTS目标") and not ielts_tasks:
        candidates.append({"事项类型": "IELTS候选任务", "建议": "请智育师根据已确认策略决定是否创建训练任务", "状态": "待人工批准"})
    return make_result("success", {"正式任务": ielts_tasks, "候选": candidates, "说明": "候选不会自动创建学生任务"})


def pbl(data: dict[str, Any]) -> dict[str, Any]:
    manifest = []
    reviews = []
    for evidence in data.get("pbl_evidence", []):
        readable = bool(evidence.get("content"))
        item = {"任务ID": evidence.get("task_id"), "来源URL": evidence.get("url"), "hash": stable_hash(evidence.get("content", "")), "可读状态": "可读" if readable else "无法读取"}
        manifest.append(item)
        reviews.append({"任务ID": evidence.get("task_id"), "AI检查结果": "待人工复核" if readable else "无法检查", "不得自动通过": True})
    return make_result("success", {"evidence_manifest": manifest, "AI检查候选": reviews})


def weekly_payload(data: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    task_rows = results["tasks"]["payload"]["records"]
    participation_rows = results["participation"]["payload"]["records"]
    payload = {
        "反馈唯一键": f"{data['student']['student_term_id']}:{data['week']['number']}",
        "student": {"id": data["student"]["id"], "name": data["student"]["name"]}, "week": data["week"],
        "data_integrity": {name: result["status"] for name, result in results.items() if name != "weekly_payload"},
        "attendance": data.get("attendance", {"状态": "缺失"}),
        "tasks": {"总数": len(task_rows), "backlog": results["tasks"]["payload"]["backlog_count"]},
        "grades": results["grades"]["payload"], "ielts": results["ielts"]["payload"], "pbl": results["pbl"]["payload"],
        "course_weekly": results["course_weekly"]["payload"],
        "participation_candidates": [x for x in participation_rows if x["status"] == "candidate"],
        "反馈状态": "数据准备",
    }
    return make_result("success", payload)


def weekly_drafts(data: dict[str, Any], payload_result: dict[str, Any]) -> dict[str, Any]:
    p = payload_result["payload"]
    drafts = {
        "任务执行AI草稿": f"本周共有{p['tasks']['总数']}项任务，当前积压{p['tasks']['backlog']}项；提交与通过需由老师核对。",
        "成绩总结AI草稿": "本段仅整理近期作业分数与变化，不推断低分原因。",
        "IELTS周总结AI草稿": "本段仅列出已确认IELTS任务；候选需经智育师批准。",
        "PBL周总结AI草稿": "本段仅整理可读证据与待人工复核项，不判断项目阶段或质量。",
        "本周总体AI草稿": "以下为待智育师审核的事实性草稿，不构成教育策略或正式发布内容。",
        "确认状态": "待智育师审核",
    }
    return make_result("success", {"drafts": drafts, "payload_hash": stable_hash(p)})


def render_html(payload: dict[str, Any], drafts: dict[str, Any]) -> str:
    escaped = json.dumps({"payload": payload, "drafts": drafts}, ensure_ascii=False, indent=2).replace("&", "&amp;").replace("<", "&lt;")
    return f"<!doctype html><meta charset='utf-8'><title>周反馈预览</title><h1>周反馈预览（待确认）</h1><pre>{escaped}</pre>"


def minimal_pdf(text: str) -> bytes:
    # A dependency-free, valid one-page PDF preview. It is a snapshot, not a typeset final report.
    safe = text.encode("ascii", "replace").decode("ascii").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:1000]
    body = f"BT /F1 10 Tf 40 760 Td ({safe}) Tj ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(body)} >>\nstream\n{body}\nendstream"]
    out = "%PDF-1.4\n"; offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out.encode()))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(out.encode()); out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets[1:])
    return (out + f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()


def publish(data: dict[str, Any], payload_result: dict[str, Any], drafts_result: dict[str, Any]) -> dict[str, Any]:
    if not data.get("publication", {}).get("approved_by_educator"):
        return make_result("blocked", {}, ["未获智育师确认；不得发布或生成对外链接"])
    snapshot = {"payload": payload_result["payload"], "drafts": drafts_result["payload"], "published_at": iso_now(), "version": 1}
    return make_result("success", {"snapshot": snapshot, "html": render_html(snapshot["payload"], snapshot["drafts"]), "pdf": minimal_pdf("Weekly feedback snapshot")})


def run_workflow(name: str, data: dict[str, Any]) -> dict[str, Any]:
    if name not in WORKFLOWS:
        raise ValueError(f"未知workflow: {name}")
    results: dict[str, Any] = {}
    results["session_content"] = session_content(data)
    results["course_weekly"] = course_weekly(data, results["session_content"])
    results["participation"] = participation(data)
    results["tasks"] = tasks(data)
    results["grades"] = grades(data)
    results["ielts"] = ielts(data, results["tasks"])
    results["pbl"] = pbl(data)
    results["weekly_payload"] = weekly_payload(data, results)
    results["weekly_drafts"] = weekly_drafts(data, results["weekly_payload"])
    results["publish"] = publish(data, results["weekly_payload"], results["weekly_drafts"])
    return results if name == "all" else {name: results[name]}


def write_artifacts(result: dict[str, Any], output_dir: Path, workflow: str, dry_run: bool = True) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    serializable = copy.deepcopy(result)
    publish_result = serializable.get("publish", {}).get("payload", {})
    pdf = publish_result.pop("pdf", None)
    html = publish_result.pop("html", None)
    result_path = output_dir / f"{workflow}_result.json"
    result_path.write_text(json.dumps({"workflow": workflow, "dry_run": dry_run, "generated_at": iso_now(), "result": serializable}, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = [result_path]
    if html is not None:
        html_path = output_dir / "weekly_feedback_preview.html"; html_path.write_text(html, encoding="utf-8"); paths.append(html_path)
    if pdf is not None:
        pdf_path = output_dir / "weekly_feedback_preview.pdf"; pdf_path.write_bytes(pdf); paths.append(pdf_path)
    return paths
