import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops import run_workflow
from student_ops.weekly_feedback_base import build_publication_fields, build_weekly_feedback_fields
from student_ops.ai import AIAdapterError, OpenAICompatibleAdapter
from student_ops.attendance_adapter import AttendanceAdapterError, build_weekly_attendance_payload
from student_ops.engine import write_artifacts
from student_ops.publishing import PDFRenderError, render_pdf
from student_ops.prompts import SESSION_COURSE_MINUTES_PROMPT_V1
from student_ops.report_template import render_weekly_report


class StudentOpsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "tests/fixtures/student_ops/week_v1.json"
        cls.data = json.loads(fixture.read_text(encoding="utf-8"))
        cls.all = run_workflow("all", cls.data)

    def test_all_workflows_have_a_repeatable_result(self):
        again = run_workflow("all", self.data)
        self.assertEqual(self.all["grades"]["payload"]["append_only_events"], again["grades"]["payload"]["append_only_events"])
        self.assertEqual(self.all["weekly_payload"]["payload"]["反馈唯一键"], "term-demo-01:3")

    def test_session_candidate_needs_a_separate_human_confirmation(self):
        records = self.all["session_content"]["payload"]["records"]
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[0]["payload"]["human_confirmation"]["confirmed_by"], "课程责任老师")
        self.assertEqual(records[1]["status"], "missing_source")
        unconfirmed = json.loads(json.dumps(self.data))
        unconfirmed["human_confirmations"] = []
        candidate = run_workflow("session_content", unconfirmed)["session_content"]["payload"]["records"][0]
        self.assertEqual(candidate["payload"]["human_confirmation"]["status"], "待确认")

    def test_invalid_ai_schema_degrades_without_formal_course_fact(self):
        bad = json.loads(json.dumps(self.data))
        bad["sessions"][0]["mock_ai_response"] = "【本节主题】不完整候选"
        result = run_workflow("session_content", bad)["session_content"]
        self.assertEqual(result["payload"]["records"][0]["status"], "invalid_schema")

    def test_openai_compatible_adapter_uses_full_prompt_and_safe_error(self):
        captured = {}
        def fake_transport(request):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return b'{"choices":[{"message":{"content":"fixture answer"}}]}'
        adapter = OpenAICompatibleAdapter("secret-value", "https://ai.example/v1", "test-model", fake_transport)
        self.assertEqual(adapter.generate(system=SESSION_COURSE_MINUTES_PROMPT_V1, user="source"), "fixture answer")
        self.assertEqual(captured["url"], "https://ai.example/v1/chat/completions")
        self.assertEqual(captured["body"]["messages"][0]["content"], SESSION_COURSE_MINUTES_PROMPT_V1)
        self.assertNotIn("secret-value", repr(adapter))
        broken = OpenAICompatibleAdapter("secret-value", "https://ai.example/v1", "test-model", lambda request: b"not-json")
        with self.assertRaisesRegex(AIAdapterError, "ai_request_failed"):
            broken.generate(system="x", user="y")

    def test_ai_failure_degrades_workflows_without_exposing_input_or_secret(self):
        class FailingAdapter:
            mode = "live"
            def generate(self, **kwargs):
                raise AIAdapterError("ai_request_failed")
        session = run_workflow("session_content", self.data, ai_adapter=FailingAdapter())["session_content"]
        self.assertEqual(session["payload"]["records"][0]["status"], "ai_failed")
        drafts = run_workflow("weekly_drafts", self.data, ai_adapter=FailingAdapter())["weekly_drafts"]
        self.assertEqual(drafts["status"], "partial")
        self.assertNotIn("任务执行AI草稿", drafts["payload"]["drafts"])
        self.assertTrue(all("学生甲" not in warning for warning in drafts["warnings"]))

    def test_task_states_deadlines_and_backlog_follow_task_rules(self):
        sample = json.loads(json.dumps(self.data))
        sample["tasks"] = [
            {"task_id": "rework", "原始Deadline": "2026-07-21", "补做Deadline": "2026-07-22", "返工Deadline": "2026-07-23", "当前提交状态": "已提交", "检查状态": "需返工"},
            {"task_id": "makeup", "原始Deadline": "2026-07-21", "补做Deadline": "2026-07-25", "当前提交状态": "未提交", "检查状态": "待确认"},
            {"task_id": "pending", "原始Deadline": "2026-07-21", "当前提交状态": "已提交", "检查状态": "待确认"},
            {"task_id": "passed", "原始Deadline": "2026-07-21", "当前提交状态": "已提交", "检查状态": "已通过"}
        ]
        rows = {x["task_id"]: x for x in run_workflow("tasks", sample)["tasks"]["payload"]["records"]}
        self.assertEqual(rows["rework"]["当前有效Deadline"], "2026-07-23")
        self.assertEqual(rows["rework"]["当前任务状态"], "需返工")
        self.assertEqual(rows["rework"]["Backlog状态"], "返工积压")
        self.assertEqual(rows["makeup"]["当前有效Deadline"], "2026-07-25")
        self.assertEqual(rows["makeup"]["Backlog状态"], "未提交")
        self.assertEqual(rows["pending"]["当前执行状态"], "已提交待审")
        self.assertNotEqual(rows["pending"]["当前任务状态"], "已完成")
        self.assertEqual(rows["passed"]["当前任务状态"], "已完成")

    def test_unmatched_participation_is_not_in_payload(self):
        rows = self.all["weekly_payload"]["payload"]["participation_candidates"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload"]["student_id"], "student-demo-01")
        self.assertEqual(self.all["participation"]["status"], "partial")

    def test_publish_creates_immutable_local_preview_only_after_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_artifacts(self.all, Path(directory), "all")
            self.assertTrue(any(path.suffix == ".html" for path in paths))
            pdf = next(path for path in paths if path.suffix == ".pdf")
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
        not_approved = json.loads(json.dumps(self.data))
        not_approved["publication"]["approved_by_educator"] = False
        self.assertEqual(run_workflow("publish", not_approved)["publish"]["status"], "blocked")

    def test_html_has_fixed_feedback_sections_and_pdf_engine_failure_is_explicit(self):
        html = run_workflow("publish", self.data)["publish"]["payload"]["html"]
        for heading in ("本周学习节奏", "课堂里发生了什么", "任务与学业进展", "IELTS 与个人项目", "下周，我们一起这样推进"):
            self.assertIn(heading, html)
        self.assertNotIn("<pre>", html)
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "page.html"; page.write_text("<p>中文</p>", encoding="utf-8")
            with self.assertRaisesRegex(PDFRenderError, "pdf_render_failed"):
                render_pdf(page, Path(directory) / "page.pdf", binary="/definitely/missing/chrome")

    def test_full_report_binds_confirmed_data_and_filters_unconfirmed_facts(self):
        html = run_workflow("publish", self.data)["publish"]["payload"]["html"]
        for marker in ("data-template='student-weekly-feedback-v1'", "学生一周出勤透视表", "任务明细", "近期作业分数", "事实性成绩说明与学校支持", "校园节能倡议", "研究问题文档", "完成IELTS阅读练习与错题归因"):
            self.assertIn(marker, html)
        self.assertNotIn("计划课程（不展示）", html)
        self.assertNotIn("计划教学内容不得展示", html)
        self.assertNotIn("AI建议但未确认", html)
        self.assertNotIn("完成一项已通过任务", html)
        self.assertIn("已提交待审", html)
        self.assertIn("<polyline", html)
        self.assertIn("不表示课程总分趋势", html)
        self.assertIn("不作为监视工具", html)
        self.assertIn("所属校区", html)
        self.assertIn("线上出勤：出勤", html)
        self.assertIn("摄像头状态暂无记录", html)
        self.assertNotIn("线下出勤：", html)
        self.assertNotIn("线下参与：", html)
        self.assertIn("@media print", html)
        self.assertIn(".toolbar,.prototype-note,.annotation{display:none!important}", html)

    def test_complete_demo_covers_fixed_weekly_report_contract(self):
        html = run_workflow("publish", self.data)["publish"]["payload"]["html"]
        for day in ("周一", "周二", "周三", "周四", "周五"):
            self.assertIn(day, html)
        for marker in (
            "本周3场已确认课程", "本周2场已确认课程", "课程问题与学校支持",
            "Backlog视图", "缺交", "返工", "待审", "Academic 6.5", "2 / 4",
            "错题归因记录", "证据收集", "利益相关者清单", "AI review候选",
            "值得肯定（确认事实）", "需要关注（确认事实）",
            "完成IELTS阅读练习与错题归因", "修订ENG4U引用分析段落", "补齐PBL证据来源链接",
        ):
            self.assertIn(marker, html)
        self.assertGreaterEqual(html.count("<polyline"), 2)
        self.assertNotIn("计划教学内容不得展示", html)

    def test_fixed_sections_render_neutral_states_when_payload_is_sparse(self):
        html = render_weekly_report({"student": {}, "week": {}, "report": {}}, {})
        for marker in (
            "本周学习节奏", "本周场次级出勤事实缺失或待确认",
            "课堂里发生了什么", "实际课程内容尚未完成老师确认",
            "任务与学业进展", "本周任务事实缺失或待同步",
            "近期作业分数", "暂无可展示的已评分任务序列",
            "IELTS 目标与周计划", "目标待确认", "PBL · 待确认项目",
            "下周，我们一起这样推进", "下周行动尚未由师生确认",
        ):
            self.assertIn(marker, html)

    def test_offline_campus_only_renders_offline_attendance_and_classroom(self):
        payload = {
            "student": {"name": "演示学生"},
            "week": {"number": 1},
            "report": {},
            "attendance": {
                "校区": "上海校区", "出勤口径": "线下", "应参加场次": 1,
                "已记录出勤场次": 1,
                "days": [{"key": "mon", "label": "周一", "date": "09/02"}],
                "slots": ["08:30–10:00"],
                "sessions": [{
                    "slot": "08:30–10:00", "day": "mon", "title": "ENG4U",
                    "线下出勤情况": "出勤", "线下出勤教室": "A201",
                    "线上出勤情况": "出勤", "摄像头开启状态": "全程开启",
                    "fact_status": "confirmed",
                }],
            },
        }
        html = render_weekly_report(payload, {})
        self.assertIn("线下出勤：出勤 · A201", html)
        self.assertNotIn("线上出勤：", html)
        self.assertNotIn("摄像头：", html)
        self.assertNotIn("关于线上画面", html)

    @staticmethod
    def base_session(record_id, term_id, student_term_id="student-term-1", date_value="2026-09-02", time="8:30-10:00", course="ENG4U", category="外教课", campus="线上", online=None, offline=None, camera=None, classroom=None):
        return {
            "record_id": record_id,
            "学生学期": [{"id": student_term_id}], "学期场次": [{"id": term_id}],
            "学生场次唯一键": f"{student_term_id}|{date_value}|{course}|{record_id}",
            "学生校区": campus, "上课日期": f"{date_value}T00:00:00.000+08:00",
            "时间": time, "课程编码": course, "场次类别": category,
            "线上出勤情况": [] if online is None else [online],
            "线下出勤情况": [] if offline is None else [offline],
            "摄像头开启状态": [] if camera is None else [camera],
            "线下出勤教室": classroom,
        }

    @staticmethod
    def term_session(record):
        return {"record_id": record["学期场次"][0]["id"], **{key: record[key] for key in ("上课日期", "时间", "课程编码", "场次类别")}}

    def test_base_adapter_online_null_future_and_same_cell_are_auditable(self):
        records = [
            self.base_session("ss-present", "ts-present", online="出勤"),
            self.base_session("ss-null", "ts-null", course="MHF4U"),
            self.base_session("ss-same-cell", "ts-same-cell", course="ESLDO", online="迟到", camera="中途关闭"),
            self.base_session("ss-future", "ts-future", date_value="2026-09-03", online="缺勤", camera="未开启"),
        ]
        payload = build_weekly_attendance_payload(
            records, [self.term_session(record) for record in records],
            student_term_id="student-term-1", week_start="2026-09-02", week_end="2026-09-08", as_of="2026-09-02",
        )
        self.assertEqual(payload["出勤口径"], "线上")
        self.assertIsNone(payload["应参加场次"])
        self.assertEqual(payload["出勤已记录场次"], 2)
        self.assertEqual(payload["出勤待记录场次"], 1)
        self.assertEqual(payload["未来场次"], 1)
        future = next(item for item in payload["sessions"] if item["source_record_id"] == "ss-future")
        self.assertEqual(future["fact_status"], "future")
        self.assertIsNone(future["线上出勤情况"])
        html = render_weekly_report({"student": {}, "week": {}, "report": {}, "attendance": payload}, {})
        self.assertEqual(html.count("未来场次 · 出勤尚未发生"), 1)
        self.assertIn("线上出勤：暂无记录", html)
        # Three records share the same date/time cell and none is overwritten.
        self.assertIn("ENG4U", html)
        self.assertIn("MHF4U", html)
        self.assertIn("ESLDO", html)
        self.assertEqual(len(payload["audit"]), 4)

    def test_base_adapter_offline_ignores_online_camera_and_preserves_empty(self):
        record = self.base_session(
            "ss-offline", "ts-offline", campus="上海", online="出勤", offline="未记录",
            camera="全程开启", classroom="A201",
        )
        payload = build_weekly_attendance_payload(
            [record], [self.term_session(record)], student_term_id="student-term-1",
            week_start="2026-09-02", week_end="2026-09-08", as_of="2026-09-02",
        )
        session = payload["sessions"][0]
        self.assertEqual(payload["出勤口径"], "线下")
        self.assertEqual(session["fact_status"], "unrecorded")
        self.assertNotIn("线上出勤情况", session)
        self.assertNotIn("摄像头开启状态", session)
        html = render_weekly_report({"student": {}, "week": {}, "report": {}, "attendance": payload}, {})
        self.assertIn("线下出勤：暂无记录", html)
        self.assertNotIn("A201", html)
        self.assertNotIn("摄像头", html)

    def test_base_adapter_surfaces_unassigned_1230_support_slot_without_fabricating_cell(self):
        student = self.base_session(
            "ss-beijing", "ts-morning", campus="北京", course="ENG4U",
        )
        morning = self.term_session(student)
        support = {
            "record_id": "ts-support-1230",
            "上课日期": "2026-09-02T00:00:00.000+08:00",
            "时间": "12:30-13:00",
            "课程编码": [],
            "场次类别": "智育辅导",
            "北京": None,
        }
        payload = build_weekly_attendance_payload(
            [student], [morning, support], student_term_id="student-term-1",
            week_start="2026-09-02", week_end="2026-09-08", as_of="2026-09-02",
        )
        self.assertEqual(payload["slots"], ["8:30-10:00"])
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(payload["diagnostics"][0]["status"], "upstream_campus_unassigned")
        self.assertEqual(payload["diagnostics"][0]["学期场次记录数"], 1)
        self.assertEqual(payload["diagnostics"][0]["学生场次记录数"], 0)
        html = render_weekly_report({"student": {}, "week": {}, "report": {}, "attendance": payload}, {})
        self.assertIn("上游存在 12:30-13:00 智育辅导", html)
        self.assertIn("校区字段为空", html)
        self.assertNotIn("12:30-13:00</td>", html)

    def test_support_slot_diagnostic_does_not_treat_unprojected_campus_as_empty(self):
        student = self.base_session("ss-beijing", "ts-morning", campus="北京")
        support_without_campus_projection = {
            "record_id": "ts-support-1230",
            "上课日期": "2026-09-02T00:00:00.000+08:00",
            "时间": "12:30-13:00", "课程编码": [], "场次类别": "智育辅导",
        }
        payload = build_weekly_attendance_payload(
            [student], [self.term_session(student), support_without_campus_projection],
            student_term_id="student-term-1", week_start="2026-09-02",
            week_end="2026-09-08", as_of="2026-09-02",
        )
        self.assertEqual(payload["diagnostics"], [])

    def test_base_adapter_rejects_unknown_campus_and_upstream_mismatch(self):
        record = self.base_session("ss-unknown", "ts-unknown", campus="未配置校区")
        with self.assertRaisesRegex(AttendanceAdapterError, "unknown_campus_scope"):
            build_weekly_attendance_payload(
                [record], [self.term_session(record)], student_term_id="student-term-1",
                week_start="2026-09-02", week_end="2026-09-08", as_of="2026-09-02",
            )
        term = self.term_session(record)
        record["学生校区"] = "线上"
        term["课程编码"] = "MHF4U"
        with self.assertRaisesRegex(AttendanceAdapterError, "upstream_mismatch"):
            build_weekly_attendance_payload(
                [record], [term], student_term_id="student-term-1",
                week_start="2026-09-02", week_end="2026-09-08", as_of="2026-09-02",
            )

    def test_weekly_payload_prefers_base_records_over_handwritten_pivot(self):
        sample = json.loads(json.dumps(self.data))
        record = self.base_session(
            "ss-production", "ts-production", student_term_id=sample["student"]["student_term_id"],
            online="出勤",
        )
        sample["week"].update({"start": "2026-09-02", "end": "2026-09-08"})
        sample["attendance"] = {"source": "handwritten_should_not_win", "days": [{"key": "fake"}]}
        sample["base_attendance"] = {
            "student_session_records": [record],
            "term_session_records": [self.term_session(record)],
            "as_of": "2026-09-02",
        }
        attendance = run_workflow("weekly_payload", sample)["weekly_payload"]["payload"]["attendance"]
        self.assertEqual(attendance["source"], "feishu_base_student_session_records")
        self.assertEqual(attendance["sessions"][0]["source_record_id"], "ss-production")
        self.assertNotEqual(attendance["days"][0]["key"], "fake")

    def test_unconfirmed_grade_explanations_do_not_publish(self):
        sample = json.loads(json.dumps(self.data))
        sample["grade_series"][0]["attention_reason"] = "未经确认的低分原因"
        sample["grade_series"][0]["attention_reason_confirmation_status"] = "待确认"
        sample["grade_series"][0]["positive_note"] = "未经确认的鼓励文字"
        sample["grade_series"][0]["positive_confirmation_status"] = "待确认"
        html = run_workflow("publish", sample)["publish"]["payload"]["html"]
        self.assertNotIn("未经确认的低分原因", html)
        self.assertNotIn("未经确认的鼓励文字", html)

    def test_unconfirmed_course_interaction_and_support_do_not_publish(self):
        sample = json.loads(json.dumps(self.data))
        course = sample["report_courses"][0]
        course["confirmed_interaction"] = "未确认互动机密文本"
        course["interaction_confirmation_status"] = "待确认"
        course["confirmed_support"] = "未确认支持机密文本"
        course["support_confirmation_status"] = "待确认"
        html = run_workflow("publish", sample)["publish"]["payload"]["html"]
        self.assertNotIn("未确认互动机密文本", html)
        self.assertNotIn("未确认支持机密文本", html)
        self.assertIn("本周无已确认互动事实", html)
        self.assertIn("学校支持安排待老师确认", html)

    def test_html_artifact_is_exact_pdf_source(self):
        published = run_workflow("publish", self.data)
        source_html = published["publish"]["payload"]["html"]
        with tempfile.TemporaryDirectory() as directory:
            paths = write_artifacts(published, Path(directory), "publish")
            html_path = next(path for path in paths if path.suffix == ".html")
            pdf_path = next(path for path in paths if path.suffix == ".pdf")
            self.assertEqual(html_path.read_text(encoding="utf-8"), source_html)
            self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF-"))

    def test_print_css_restores_a4_grids_after_mobile_media_query(self):
        html = run_workflow("publish", self.data)["publish"]["payload"]["html"]
        for rule in (
            ".report-header{grid-template-columns:minmax(0,1fr) 230px",
            ".story-grid{grid-template-columns:1.1fr 1fr 1fr",
            ".backlog-grid{grid-template-columns:repeat(3,minmax(0,1fr))",
            ".progress-layout{grid-template-columns:1.15fr .85fr",
            ".dual-module{grid-template-columns:.9fr 1.25fr",
            ".evidence{grid-template-columns:repeat(3,minmax(0,1fr))",
            ".next-week{grid-template-columns:1fr 1.4fr",
            ".privacy-note{margin:8px 0 0",
        ):
            self.assertIn(rule, html)

    def test_publish_is_idempotent_and_requires_key_fact_modules(self):
        first = run_workflow("publish", self.data)["publish"]["payload"]["snapshot"]
        second = run_workflow("publish", self.data)["publish"]["payload"]["snapshot"]
        self.assertEqual(first["published_id"], second["published_id"])
        self.assertEqual(first, second)
        blocked = json.loads(json.dumps(self.data))
        blocked["human_confirmations"] = []
        result = run_workflow("publish", blocked)["publish"]
        self.assertEqual(result["status"], "blocked")
        self.assertIn("course_weekly", result["warnings"][0])

    def test_selector_runs_only_its_minimal_dependency_graph(self):
        minimal = {"week": self.data["week"], "tasks": []}
        self.assertEqual(run_workflow("tasks", minimal)["tasks"]["status"], "success")
        self.assertEqual(run_workflow("session_content", {"sessions": []})["session_content"]["status"], "partial")

    def test_blocked_module_skips_its_draft_and_marks_partial(self):
        blocked = json.loads(json.dumps(self.data))
        blocked["human_confirmations"] = []
        drafts = run_workflow("weekly_drafts", blocked)["weekly_drafts"]
        self.assertEqual(drafts["status"], "partial")
        self.assertNotIn("课程学习AI草稿", drafts["payload"]["drafts"])
        self.assertTrue(drafts["warnings"])

    def test_pbl_unreadable_evidence_is_not_graded(self):
        review = self.all["pbl"]["payload"]["AI检查候选"][1]
        self.assertEqual(review["AI检查结果"], "无法判断")
        self.assertTrue(review["不得自动通过"])
        self.assertEqual(self.all["pbl"]["status"], "partial")
        self.assertTrue(self.all["pbl"]["warnings"])

    def test_structured_candidates_accept_fence_and_reject_missing_fields(self):
        self.assertEqual(self.all["course_weekly"]["status"], "success")
        self.assertEqual(self.all["ielts"]["payload"]["候选"][0]["状态"], "待人工批准")
        invalid = json.loads(json.dumps(self.data))
        invalid["mock_structured_responses"]["course_weekly"] = '{"内容":"only"}'
        self.assertEqual(run_workflow("course_weekly", invalid)["course_weekly"]["status"], "partial")

    def test_participation_source_ai_and_no_ielts_strategy_degrade_safely(self):
        sample = json.loads(json.dumps(self.data))
        sample["participation_events"] = []
        sample["participation_sources"] = [{"session_id": "session-demo-01", "text": "甲同学解释步骤", "mock_ai_response": '[{"speaker":"学生甲","category":"回答问题","direction":"正向","objective_fact":"解释步骤","source_ref":"line-1"}]'}]
        result = run_workflow("participation", sample)["participation"]
        self.assertEqual(result["payload"]["records"][0]["status"], "candidate")
        sample["participation_sources"][0]["mock_ai_response"] = "not-json"
        failed = run_workflow("participation", sample)["participation"]
        self.assertEqual(failed["status"], "partial")
        self.assertEqual(failed["payload"]["records"][0]["status"], "ai_failed")
        sample["student"].pop("IELTS已确认策略")
        self.assertEqual(run_workflow("ielts", sample)["ielts"]["payload"]["候选"], [])

    def test_weekly_feedback_base_contract_only_writes_editable_fields(self):
        result = run_workflow("all", self.data)
        payload = result["weekly_payload"]["payload"]
        fields = build_weekly_feedback_fields(
            payload,
            result["weekly_drafts"],
            educator_overrides={"课程学习AI草稿": "老师修订后的课程学习反馈"},
        )
        self.assertEqual(fields["反馈唯一键"], payload["反馈唯一键"])
        self.assertEqual(fields["反馈状态"], ["草稿"])
        self.assertEqual(fields["课程学习AI草稿"], "老师修订后的课程学习反馈")
        self.assertNotIn("attendance", fields)
        with self.assertRaises(ValueError):
            build_weekly_feedback_fields(payload, result["weekly_drafts"], educator_overrides={"学生学期": "不得通过预览改关联"})

    def test_publication_base_contract_requires_complete_versioned_urls(self):
        fields = build_publication_fields(
            version="v2026w1-r1",
            published_at="2026-09-05 18:00",
            html_url="https://feedback.example/v2026w1-r1",
            pdf_url="https://feedback.example/v2026w1-r1.pdf",
        )
        self.assertEqual(fields["反馈状态"], ["已发布"])
        self.assertEqual(fields["撤销状态"], ["有效"])
        with self.assertRaises(ValueError):
            build_publication_fields(version="", published_at="", html_url="", pdf_url="")


if __name__ == "__main__":
    unittest.main()
