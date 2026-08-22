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

    def test_session_requires_source_and_never_promotes_candidate(self):
        records = self.all["session_content"]["payload"]["records"]
        self.assertEqual(records[0]["status"], "success")
        self.assertEqual(records[0]["payload"]["confirmation_status"], "已确认")
        self.assertEqual(records[1]["status"], "missing_source")

    def test_invalid_ai_schema_degrades_without_formal_course_fact(self):
        bad = json.loads(json.dumps(self.data))
        bad["sessions"][0]["mock_ai_response"] = "【本节主题】不完整候选"
        result = run_workflow("session_content", bad)["session_content"]
        self.assertEqual(result["payload"]["records"][0]["status"], "invalid_schema")

    def test_deadline_priority_and_backlog_are_deterministic(self):
        first = self.all["tasks"]["payload"]["records"][0]
        self.assertEqual(first["当前有效Deadline"], "2026-07-24")
        self.assertEqual(first["当前任务状态"], "已提交待检查")
        self.assertNotEqual(first["当前任务状态"], "已通过")

    def test_unmatched_participation_is_not_in_payload(self):
        rows = self.all["weekly_payload"]["payload"]["participation_candidates"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload"]["student_id"], "student-demo-01")

    def test_publish_creates_immutable_local_preview_only_after_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_artifacts(self.all, Path(directory), "all")
            self.assertTrue(any(path.suffix == ".html" for path in paths))
            pdf = next(path for path in paths if path.suffix == ".pdf")
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
        not_approved = json.loads(json.dumps(self.data))
        not_approved["publication"]["approved_by_educator"] = False
        self.assertEqual(run_workflow("publish", not_approved)["publish"]["status"], "blocked")

    def test_pbl_unreadable_evidence_is_not_graded(self):
        review = self.all["pbl"]["payload"]["AI检查候选"][1]
        self.assertEqual(review["AI检查结果"], "无法检查")
        self.assertTrue(review["不得自动通过"])


if __name__ == "__main__":
    unittest.main()
