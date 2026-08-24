import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.weekly_feedback_base_input import build_weekly_feedback_input


class WeeklyFeedbackBaseInputTests(unittest.TestCase):
    def test_uses_only_confirmed_course_content_and_interaction(self):
        term = {"record_id": "term1"}
        term_sessions = [
            {"record_id": "s1", "课程编码": "MHF4U", "上课日期": "2026-09-02", "时间": "08:00-10:00", "场次类别": "外教课", "内容确认状态": ["已确认"], "课程内容总结": "确认内容"},
            {"record_id": "s2", "课程编码": "MHF4U", "上课日期": "2026-09-03", "时间": "08:00-10:00", "场次类别": "外教课", "内容确认状态": ["待确认"], "课程内容总结": "不可用内容"},
        ]
        student_sessions = [
            {"record_id": "ss1", "学生学期": [{"id": "term1"}], "学期场次": [{"id": "s1"}], "上课日期": "2026-09-02", "时间": "08:00-10:00", "课程编码": "MHF4U", "场次类别": "外教课", "学生场次唯一键": "key1", "学生校区": "线上", "线上出勤情况": "出勤", "互动情况": ["已确认"], "互动内容": "解释了计算步骤"},
            {"record_id": "ss2", "学生学期": [{"id": "term1"}], "学期场次": [{"id": "s2"}], "上课日期": "2026-09-03", "时间": "08:00-10:00", "课程编码": "MHF4U", "场次类别": "外教课", "学生场次唯一键": "key2", "学生校区": "线上", "线上出勤情况": "出勤", "互动情况": ["有可用互动证据"], "互动内容": "尚未确认"},
        ]
        data = build_weekly_feedback_input(student_term=term, student_name="学生甲", week_label="第1周", week_start="2026-09-02", week_end="2026-09-05", as_of="2026-09-06", student_sessions=student_sessions, term_sessions=term_sessions, student_tasks=[], grade_records=[])
        self.assertEqual(data["sessions"][0]["source_text"], "确认内容")
        self.assertEqual(data["sessions"][1]["source_text"], "")
        self.assertEqual(data["report_courses"][0]["actual_content"], "确认内容")
        self.assertEqual(data["report_courses"][0]["confirmed_interaction"], "解释了计算步骤")
        self.assertEqual(data["report_courses"][0]["interaction_confirmation_status"], "已确认")

    def test_requires_the_linked_term_session_export(self):
        with self.assertRaisesRegex(ValueError, "missing_linked_term_sessions"):
            build_weekly_feedback_input(student_term={"record_id": "term1"}, student_name="学生甲", week_label=1, week_start="2026-09-02", week_end="2026-09-05", as_of="2026-09-06", student_sessions=[{"record_id": "ss1", "学生学期": [{"id": "term1"}], "学期场次": [{"id": "missing"}], "上课日期": "2026-09-02"}], term_sessions=[], student_tasks=[], grade_records=[])


if __name__ == "__main__":
    unittest.main()
