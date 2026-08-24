import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops import run_workflow
from student_ops.ai import AIAdapterError, OpenAICompatibleAdapter
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


if __name__ == "__main__":
    unittest.main()
