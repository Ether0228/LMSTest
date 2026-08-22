import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops import run_workflow
from student_ops.engine import write_artifacts


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
        self.assertEqual(review["AI检查结果"], "无法检查")
        self.assertTrue(review["不得自动通过"])


if __name__ == "__main__":
    unittest.main()
