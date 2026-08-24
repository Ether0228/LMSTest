import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.weekly_feedback_drafts import apply_feedback_record, resolve_drafts
from student_ops.report_template import render_weekly_report


class WeeklyFeedbackDraftTests(unittest.TestCase):
    def test_base_teacher_text_overrides_generated_text(self):
        drafts = resolve_drafts({"本周总体AI草稿": "AI旧稿"}, {"本周总体AI草稿": "老师已改", "下周学生行动": "完成复盘"})
        self.assertEqual(drafts["本周总体AI草稿"], "老师已改")
        self.assertEqual(drafts["下周学生行动"], "完成复盘")

    def test_action_is_not_public_until_feedback_is_confirmed(self):
        payload = {"confirmed_next_actions": []}
        draft = {"下周学生行动": "完成复盘", "下周学校支持": "老师核对"}
        preview, _ = apply_feedback_record(payload, draft, {"反馈状态": ["草稿"]})
        self.assertEqual(preview["confirmed_next_actions"], [])
        confirmed, _ = apply_feedback_record(payload, draft, {"反馈状态": ["已确认"]})
        self.assertEqual(confirmed["confirmed_next_actions"][0]["action"], "完成复盘")

    def test_render_uses_teacher_modified_summary(self):
        html = render_weekly_report({"student": {"name": "学生甲"}, "week": {"number": 1}, "attendance": {}, "task_records": [], "report": {}}, {"智育师修改稿": "这段来自老师修改"})
        self.assertIn("这段来自老师修改", html)


if __name__ == "__main__":
    unittest.main()
