import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from plan_schoology_course_task_import import build_import_plan


class SchoologyCourseTaskImportPlanTests(unittest.TestCase):
    def test_marks_missing_course_without_creating_or_guessing_task_type(self):
        plan = build_import_plan(
            snapshot={
                "course_sections": [
                    {"section_nid": "s1", "course_code": "MHF4U"},
                    {"section_nid": "s2", "course_code": "CIA4U"},
                ],
                "grade_items": [
                    {"section_nid": "s1", "grade_item_nid": "a1", "title": "Quiz"},
                    {"section_nid": "s2", "grade_item_nid": "a2", "title": "Test"},
                ],
            },
            base_courses=[{"课程": ["MHF4U"]}],
            base_tasks=[],
            semester="26-S6",
        )
        self.assertEqual(plan["待建学期课程"], ["CIA4U"])
        self.assertEqual(plan["统计"]["可供确认"], 1)
        self.assertEqual(plan["统计"]["受课程建档阻塞"], 1)
        self.assertEqual(plan["课程任务候选"][0]["拟写入任务类型"], "待课程负责人确认（不得由系统推断）")

