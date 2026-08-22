"""Deterministic V1 workflow engine for the Student Learning Operations System.

The engine is intentionally fixture-first: it makes auditable artefacts, never
contacts Feishu/Schoology, and never turns an AI candidate into a formal fact.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ai import AIAdapterError, FixtureAIAdapter
from .prompts import SESSION_COURSE_MINUTES_PROMPT_V1
from .publishing import PDFRenderError, render_pdf, render_weekly_html
from .validation import CandidateSchemaError, parse_json_candidate, require_list, require_object

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


def session_prompt_user(session: dict[str, Any]) -> str:
    return f"课程：{session.get('course_code', '未提供')}\n场次：{session.get('session_id', '未提供')}\n\n已确认纪要来源：\n{session.get('source_text', '')}"


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


def session_content(data: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    confirmations = {x.get("session_id"): x for x in data.get("human_confirmations", [])}
    results = []
    for session in data.get("sessions", []):
        source = str(session.get("source_text") or "").strip()
        base = {"session_id": session.get("session_id"), "schema_version": "session_course_minutes_v1"}
        if not source:
            results.append(make_result("missing_source", base, ["缺少已确认的纪要来源；未调用AI"]))
            continue
        try:
            candidate = ai_adapter.generate(system=SESSION_COURSE_MINUTES_PROMPT_V1, user=session_prompt_user(session), fixture_response=session.get("mock_ai_response"))
        except AIAdapterError as error:
            results.append(make_result("ai_failed", {**base, "ai_mode": getattr(ai_adapter, "mode", "unknown")}, [str(error)]))
            continue
        sections, parse_errors = parse_six_sections(candidate)
        errors = parse_errors + validate_session_minutes(candidate, sections)
        if errors:
            results.append(make_result("invalid_schema", {**base, "candidate": candidate}, errors))
            continue
        # The AI candidate is never itself a confirmation. Confirmation is a
        # separately supplied human fact, matching SESSION-05/06.
        human_confirmation = confirmations.get(session.get("session_id"), {})
        results.append(make_result("success", {
            **base, "candidate": candidate, "structured": sections,
            "input_hash": stable_hash(source),
            "human_confirmation": {
                "status": human_confirmation.get("status", "待确认"),
                "confirmed_by": human_confirmation.get("confirmed_by"),
                "confirmed_at": human_confirmation.get("confirmed_at"),
            },
        }))
    overall = "success" if results and all(x["status"] == "success" for x in results) else "partial"
    return make_result(overall, {"records": results})


COURSE_FIELDS = {"内容", "进度", "重点", "任务Deadline", "测评", "中教支持", "课程问题", "下周方向"}


def course_weekly(data: dict[str, Any], sessions_result: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    confirmed = []
    for row in sessions_result["payload"]["records"]:
        if row["status"] == "success" and row["payload"]["human_confirmation"].get("status") == "已确认":
            confirmed.append(row["payload"])
    if not confirmed:
        return make_result("blocked", {"records": []}, ["没有已确认的实际课程内容，不能以计划内容替代"])
    facts = [{"session_id": r["session_id"], "sections": r["structured"]} for r in confirmed]
    try:
        candidate = require_object(parse_json_candidate(ai_adapter.generate(
            system="只根据已确认的实际课程场次事实生成课程周摘要JSON，不补充计划内容。",
            user=json.dumps(facts, ensure_ascii=False), fixture_response=data.get("mock_structured_responses", {}).get("course_weekly"),
        )), COURSE_FIELDS)
    except (AIAdapterError, CandidateSchemaError) as error:
        return make_result("partial", {"records": []}, [f"课程周AI候选失败：{error}"])
    record = {
        "课程周唯一键": f"{data['course']['course_offering_id']}:{data['week']['number']}:全班",
        "课程开设": data["course"]["course_offering_id"], "教学周": data["week"]["number"],
        "本周内容AI候选": candidate["内容"], "实际进度候选": candidate["进度"], "本周重点候选": candidate["重点"],
        "任务与Deadline": candidate["任务Deadline"], "测评": candidate["测评"], "中教支持": candidate["中教支持"],
        "课程问题": candidate["课程问题"], "下周方向": candidate["下周方向"], "来源场次": [r["session_id"] for r in confirmed],
        "确认状态": "待课程责任老师确认", "事实截止时间": data["week"]["end"],
    }
    return make_result("success", {"records": [record]})


def participation(data: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    roster = set(data.get("student", {}).get("aliases", [])) | {data.get("student", {}).get("name", "")}
    records, events = [], data.get("participation_events", [])
    for source in data.get("participation_sources", []):
        try:
            extracted = require_list(parse_json_candidate(ai_adapter.generate(
                system="从课堂纪要/逐字稿提取客观互动JSON，不推测态度或能力。",
                user=str(source.get("text", "")), fixture_response=source.get("mock_ai_response"),
            )), {"speaker", "category", "direction", "objective_fact", "source_ref"}, {"direction": {"正向", "中性", "需支持"}})
            events += [{"session_id": source.get("session_id"), "speaker": x["speaker"], "category": x["category"], "direction": x["direction"], "evidence": x["objective_fact"], "source": x["source_ref"]} for x in extracted]
        except (AIAdapterError, CandidateSchemaError) as error:
            records.append(make_result("ai_failed", {"session_id": source.get("session_id")}, [str(error)]))
    for event in events:
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
    overall = "partial" if any(row["status"] == "unmatched" for row in records) else "success"
    warnings = ["存在无法唯一匹配的互动候选，已排除在对外事实之外"] if overall == "partial" else []
    return make_result(overall, {"records": records}, warnings)


def effective_deadline(task: dict[str, Any]) -> str | None:
    """TASK-002: use rework deadline only while the task is in rework."""
    if task.get("检查状态") in ("需返工", "已返工待确认") and task.get("返工Deadline"):
        return task["返工Deadline"]
    return task.get("补做Deadline") or task.get("原始Deadline")


def tasks(data: dict[str, Any]) -> dict[str, Any]:
    today = date.fromisoformat(data["week"]["end"])
    records = []
    for task in data.get("tasks", []):
        record = copy.deepcopy(task)
        deadline = effective_deadline(task)
        record["当前有效Deadline"] = deadline
        submission = task.get("当前提交状态", "未提交")
        check = task.get("检查状态", "待确认")
        submitted = submission in ("已提交", "已重新提交")
        rework_resubmitted = submission == "已重新提交"
        passed = check == "已通过"
        overdue = bool(deadline and date.fromisoformat(deadline) < today)
        if passed:
            task_state, display_state, backlog = "已完成", "已通过", "正常"
        elif check == "需返工":
            task_state, display_state = "需返工", "需返工"
            backlog = "返工积压" if overdue and not rework_resubmitted else "正常"
        elif check == "已返工待确认":
            task_state, display_state, backlog = "待确认", "已提交待审", "正常"
        elif submitted:
            task_state, display_state, backlog = "待确认", "已提交待审", "正常"
        elif overdue:
            task_state, display_state, backlog = "未完成", "未提交", "缺交积压"
        else:
            task_state, display_state, backlog = "未完成", "未提交", "未提交"
        record["Backlog状态"] = backlog
        record["积压天数"] = max((today - date.fromisoformat(deadline)).days, 0) if backlog in ("缺交积压", "返工积压") else 0
        record["当前任务状态"] = task_state
        record["当前执行状态"] = display_state
        records.append(record)
    return make_result("success", {"records": records, "backlog_count": sum(x["Backlog状态"] in ("缺交积压", "返工积压") for x in records)})


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


def ielts(data: dict[str, Any], task_result: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    ielts_tasks = [x for x in task_result["payload"]["records"] if x.get("所属模块") == "IELTS"]
    candidates = []
    strategy = data.get("student", {}).get("IELTS已确认策略")
    if data.get("student", {}).get("IELTS目标") and strategy:
        try:
            candidate = require_object(parse_json_candidate(ai_adapter.generate(
                system="根据已确认IELTS策略和任务容量生成候选JSON；不得创建正式任务。",
                user=json.dumps({"目标": data["student"]["IELTS目标"], "策略": strategy, "现有任务": ielts_tasks}, ensure_ascii=False), fixture_response=data.get("mock_structured_responses", {}).get("ielts"),
            )), {"标题", "原因", "建议Deadline", "需讨论"})
            candidates.append({"事项类型": "IELTS候选任务", **candidate, "状态": "待人工批准"})
        except (AIAdapterError, CandidateSchemaError) as error:
            return make_result("partial", {"正式任务": ielts_tasks, "候选": [], "说明": "候选不会自动创建学生任务"}, [f"IELTS候选失败：{error}"])
    return make_result("success", {"正式任务": ielts_tasks, "候选": candidates, "说明": "候选不会自动创建学生任务"})


def pbl(data: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    manifest = []
    reviews = []
    for evidence in data.get("pbl_evidence", []):
        readable = bool(evidence.get("content"))
        item = {"任务ID": evidence.get("task_id"), "来源URL": evidence.get("url"), "hash": stable_hash(evidence.get("content", "")), "可读状态": "可读" if readable else "无法读取"}
        manifest.append(item)
        if not readable or not evidence.get("completion_standard"):
            reviews.append({"任务ID": evidence.get("task_id"), "AI检查结果": "无法判断", "说明": "证据不可读或缺少已确认完成标准", "缺失项": "待补充", "建议复核": "人工确认", "不得自动通过": True})
            continue
        try:
            review = require_object(parse_json_candidate(ai_adapter.generate(
                system="仅按已确认完成标准检查PBL证据JSON，不自动通过任务或推进项目阶段。",
                user=json.dumps({"standard": evidence["completion_standard"], "evidence": evidence["content"]}, ensure_ascii=False), fixture_response=evidence.get("mock_ai_response"),
            )), {"结果", "说明", "缺失项", "建议复核"}, {"结果": {"达标", "基本达标", "需修改", "无法判断"}})
            reviews.append({"任务ID": evidence.get("task_id"), "AI检查结果": review["结果"], "说明": review["说明"], "缺失项": review["缺失项"], "建议复核": review["建议复核"], "不得自动通过": True})
        except (AIAdapterError, CandidateSchemaError) as error:
            reviews.append({"任务ID": evidence.get("task_id"), "AI检查结果": "无法判断", "说明": "AI检查失败", "缺失项": "待人工检查", "建议复核": "人工确认", "不得自动通过": True})
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


def weekly_drafts(data: dict[str, Any], payload_result: dict[str, Any], ai_adapter: Any) -> dict[str, Any]:
    p = payload_result["payload"]
    integrity = p.get("data_integrity", {})
    modules = {
        "course_weekly": ("课程学习AI草稿", "本段仅使用已确认的实际课堂内容和已确认互动事实。"),
        "tasks": ("任务执行AI草稿", f"本周共有{p['tasks']['总数']}项任务，当前积压{p['tasks']['backlog']}项；提交与通过需由老师核对。"),
        "grades": ("成绩总结AI草稿", "本段仅整理近期作业分数与变化，不推断低分原因。"),
        "ielts": ("IELTS周总结AI草稿", "本段仅列出已确认IELTS任务；候选需经智育师批准。"),
        "pbl": ("PBL周总结AI草稿", "本段仅整理可读证据与待人工复核项，不判断项目阶段或质量。"),
    }
    drafts, warnings = {}, []
    responses = data.get("mock_weekly_responses", {})
    slices = {"course_weekly": p.get("course_weekly"), "tasks": p.get("tasks"), "grades": p.get("grades"), "ielts": p.get("ielts"), "pbl": p.get("pbl")}
    for module, (field, fallback) in modules.items():
        if integrity.get(module) == "blocked":
            warnings.append(f"{module}为blocked，未生成{field}")
        else:
            try:
                drafts[field] = ai_adapter.generate(
                    system="你是学生学习运营系统的草稿助手。只依据输入事实，不作人格、动机、质量或教育策略判断。输出中文候选草稿。",
                    user=f"模块：{module}\n事实摘要：{json.dumps(slices[module], ensure_ascii=False, sort_keys=True)}",
                    fixture_response=responses.get(module, fallback if getattr(ai_adapter, "mode", "") == "fixture" else None),
                )
            except AIAdapterError as error:
                warnings.append(f"{module} AI失败：{error}")
    try:
        drafts["本周总体AI草稿"] = ai_adapter.generate(
            system="你是学生学习运营系统的草稿助手。只综合可用事实，不作教育策略或最终判断。",
            user=f"可用模块状态：{json.dumps(integrity, ensure_ascii=False, sort_keys=True)}\n已生成草稿：{json.dumps(drafts, ensure_ascii=False, sort_keys=True)}",
            fixture_response=responses.get("overall", "以下为仅基于可用模块的待审核事实性草稿，不构成教育策略或正式发布内容。" if getattr(ai_adapter, "mode", "") == "fixture" else None),
        )
    except AIAdapterError as error:
        warnings.append(f"overall AI失败：{error}")
    drafts["确认状态"] = "待智育师审核"
    status = "partial" if warnings else "success"
    return make_result(status, {"drafts": drafts, "payload_hash": stable_hash(p)}, warnings)


def publish(data: dict[str, Any], payload_result: dict[str, Any], drafts_result: dict[str, Any]) -> dict[str, Any]:
    publication = data.get("publication", {})
    if not publication.get("approved_by_educator"):
        return make_result("blocked", {}, ["未获智育师确认；不得发布或生成对外链接"])
    if not publication.get("approved_at") or not publication.get("version"):
        return make_result("blocked", {}, ["缺少明确的人工确认时间或发布版本；不得产生不稳定快照"])
    critical_modules = ("course_weekly", "tasks", "grades", "ielts", "pbl")
    blocked = [name for name in critical_modules if payload_result["payload"].get("data_integrity", {}).get(name) == "blocked"]
    if blocked:
        return make_result("blocked", {}, [f"关键事实模块blocked：{', '.join(blocked)}；不得发布"])
    payload_hash = stable_hash(payload_result["payload"])
    snapshot = {
        "payload": payload_result["payload"], "drafts": drafts_result["payload"],
        "approved_at": publication["approved_at"], "version": publication["version"],
        "published_id": stable_hash({"payload_hash": payload_hash, "approved_at": publication["approved_at"], "version": publication["version"]})[:24],
    }
    return make_result("success", {"snapshot": snapshot, "html": render_weekly_html(snapshot["payload"], snapshot["drafts"]["drafts"])})


def run_workflow(name: str, data: dict[str, Any], ai_adapter: Any | None = None) -> dict[str, Any]:
    if name not in WORKFLOWS:
        raise ValueError(f"未知workflow: {name}")
    results: dict[str, Any] = {}
    ai_adapter = ai_adapter or FixtureAIAdapter()
    dependencies = {
        "session_content": (), "course_weekly": ("session_content",), "participation": (), "tasks": (), "grades": (),
        "ielts": ("tasks",), "pbl": (), "weekly_payload": ("course_weekly", "participation", "tasks", "grades", "ielts", "pbl"),
        "weekly_drafts": ("weekly_payload",), "publish": ("weekly_payload", "weekly_drafts"),
    }
    runners: dict[str, Callable[[], dict[str, Any]]] = {
        "session_content": lambda: session_content(data, ai_adapter), "course_weekly": lambda: course_weekly(data, results["session_content"], ai_adapter),
        "participation": lambda: participation(data, ai_adapter), "tasks": lambda: tasks(data), "grades": lambda: grades(data),
        "ielts": lambda: ielts(data, results["tasks"], ai_adapter), "pbl": lambda: pbl(data, ai_adapter),
        "weekly_payload": lambda: weekly_payload(data, results), "weekly_drafts": lambda: weekly_drafts(data, results["weekly_payload"], ai_adapter),
        "publish": lambda: publish(data, results["weekly_payload"], results["weekly_drafts"]),
    }
    def execute(target: str) -> None:
        if target in results:
            return
        for dependency in dependencies[target]:
            execute(dependency)
        results[target] = runners[target]()
    if name == "all":
        for workflow in dependencies:
            execute(workflow)
        return results
    execute(name)
    return {name: results[name]}


def write_artifacts(result: dict[str, Any], output_dir: Path, workflow: str, dry_run: bool = True, chrome_binary: str | None = None) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    serializable = copy.deepcopy(result)
    publish_result = serializable.get("publish", {}).get("payload", {})
    html = publish_result.pop("html", None)
    paths = []
    if html is not None:
        html_path = output_dir / "weekly_feedback_preview.html"
        html_path.write_text(html, encoding="utf-8")
        paths.append(html_path)
        try:
            pdf_path = output_dir / "weekly_feedback_preview.pdf"
            render_pdf(html_path, pdf_path, chrome_binary)
            publish_result["pdf_status"] = "success"
            paths.append(pdf_path)
        except PDFRenderError as error:
            publish_result["pdf_status"] = "failed"
            serializable.setdefault("publish", {}).setdefault("warnings", []).append(str(error))
    result_path = output_dir / f"{workflow}_result.json"
    result_path.write_text(json.dumps({"workflow": workflow, "dry_run": dry_run, "generated_at": iso_now(), "result": serializable}, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.insert(0, result_path)
    return paths
