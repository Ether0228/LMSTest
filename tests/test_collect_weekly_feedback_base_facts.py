import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from collect_weekly_feedback_base_facts import selected_student_sessions


class CollectWeeklyFeedbackBaseFactsTests(unittest.TestCase):
    def test_filters_by_link_id_and_existing_teaching_week_not_name(self):
        rows = [
            {"record_id": "right", "学生学期": [{"id": "term1", "name": "同名学生"}], "教学周": "第2周"},
            {"record_id": "wrong-term", "学生学期": [{"id": "term2", "name": "同名学生"}], "教学周": "第2周"},
            {"record_id": "wrong-week", "学生学期": [{"id": "term1"}], "教学周": "第1周"},
        ]
        self.assertEqual([row["record_id"] for row in selected_student_sessions(rows, student_term_id="term1", week_number=2)], ["right"])


if __name__ == "__main__":
    unittest.main()
