import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.course_session_mapper import build_course_source_write_plan


class CourseSessionMapperTests(unittest.TestCase):
    def test_maps_only_exact_explicit_lesson_date(self):
        source = {"学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02", "文档token": "doc1", "智能纪要URL": "https://x/docx/doc1", "正文": "正文"}
        sessions = [{"record_id": "session1", "学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02"}]
        plan = build_course_source_write_plan([source], sessions)
        self.assertEqual(plan["session_updates"][0]["record_id"], "session1")
        self.assertEqual(plan["session_updates"][0]["fields"]["内容生成状态"], ["待生成"])
        self.assertEqual(plan["session_updates"][0]["fields"]["内容来源链接"], "https://x/docx/doc1")
        self.assertFalse(plan["exceptions"])

    def test_refuses_message_time_as_lesson_date(self):
        source = {"学期": "S6", "课程编码": "MHF4U", "消息发送时间": "2026-09-02T12:00:00+08:00", "文档token": "doc1"}
        plan = build_course_source_write_plan([source], [])
        self.assertEqual(plan["session_updates"], [])
        self.assertEqual(plan["exceptions"][0]["类型"], "待补实际上课日期")

    def test_refuses_ambiguous_sessions(self):
        source = {"学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02", "文档token": "doc1"}
        sessions = [
            {"record_id": "session1", "学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02"},
            {"record_id": "session2", "学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02"},
        ]
        plan = build_course_source_write_plan([source], sessions)
        self.assertEqual(plan["exceptions"][0]["类型"], "学期场次无法唯一匹配")

    def test_refuses_to_overwrite_a_different_existing_source(self):
        source = {"学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02", "文档token": "doc1", "智能纪要URL": "https://x/docx/doc1"}
        sessions = [{"record_id": "session1", "学期": "S6", "课程编码": "MHF4U", "上课日期": "2026-09-02", "内容来源链接": "https://x/docx/old"}]
        plan = build_course_source_write_plan([source], sessions)
        self.assertEqual(plan["session_updates"], [])
        self.assertEqual(plan["exceptions"][0]["类型"], "场次已有不同内容来源")


if __name__ == "__main__":
    unittest.main()
