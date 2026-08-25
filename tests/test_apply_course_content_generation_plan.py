import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from apply_course_content_generation_plan import validate


class ApplyCourseContentGenerationPlanTests(unittest.TestCase):
    def test_allows_candidate_but_not_confirmation_or_summary(self):
        plan = {"session_updates": [{"record_id": "s1", "fields": {"课程内容AI候选": "候选", "内容确认状态": ["待确认"]}}]}
        self.assertEqual(len(validate(plan)), 1)
        with self.assertRaisesRegex(RuntimeError, "ai_candidate_must_not_confirm_content"):
            validate({"session_updates": [{"record_id": "s1", "fields": {"内容确认状态": ["已确认"]}}]})
        with self.assertRaisesRegex(RuntimeError, "unapproved"):
            validate({"session_updates": [{"record_id": "s1", "fields": {"课程内容总结": "不可由AI确认"}}]})
