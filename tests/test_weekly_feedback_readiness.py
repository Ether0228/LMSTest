import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.weekly_feedback_readiness import assess_readiness


class WeeklyFeedbackReadinessTests(unittest.TestCase):
    def test_reports_specific_missing_gates(self):
        result = assess_readiness(env={}, students=[{}], course_tasks=[{}], term_sessions=[{"上课日期": "2026-09-02", "内容确认状态": ["待确认"]}], as_of="2026-09-03")
        self.assertFalse(result["ready_for_real_e2e"])
        self.assertIn("live_ai", result["next_blockers"])
        self.assertIn("ended_confirmed_course_content", result["next_blockers"])

    def test_accepts_complete_minimal_readiness(self):
        env = {name: True for name in ("AI_API_KEY", "AI_BASE_URL", "AI_MODEL", "SCHOOLOGY_COOKIES", "SCHOOLOGY_SECTION_NIDS")}
        result = assess_readiness(env=env, students=[{"Schoology学生UID": "u1"}], course_tasks=[{"SchoologySectionNID": "s1", "Schoology作业NID": "a1"}], term_sessions=[{"上课日期": "2026-09-02", "内容确认状态": ["已确认"]}], as_of="2026-09-03")
        self.assertTrue(result["ready_for_real_e2e"])


if __name__ == "__main__":
    unittest.main()
