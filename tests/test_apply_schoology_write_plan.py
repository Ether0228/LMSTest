import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from apply_schoology_write_plan import validate_plan


class ApplySchoologyWritePlanTests(unittest.TestCase):
    def test_requires_explicit_partial_approval(self):
        plan = {"student_task_updates": [{"record_id": "task1", "fields": {"当前提交状态": ["已提交"]}}], "grade_updates": [], "exceptions": [{"类型": "未匹配课程任务"}]}
        with self.assertRaisesRegex(RuntimeError, "schoology_plan_contains_exceptions"):
            validate_plan(plan, allow_partial=False)
        tasks, grades = validate_plan(plan, allow_partial=True)
        self.assertEqual(tasks[0]["record_id"], "task1")
        self.assertEqual(grades, [])

    def test_rejects_unapproved_task_field(self):
        plan = {"student_task_updates": [{"record_id": "task1", "fields": {"完成状态": ["已提交"]}}]}
        with self.assertRaisesRegex(RuntimeError, "schoology_plan_contains_unapproved_fields"):
            validate_plan(plan, allow_partial=False)

    def test_allows_new_grade_record_only_with_stable_ids_and_links(self):
        plan = {"grade_updates": [{"record_id": None, "fields": {"学生UID": "u1", "SectionNID": "s1", "作业NID": "a1", "所属课程任务": [{"id": "ct1"}], "学生学期任务": [{"id": "st1"}], "得分": 80, "满分": 100}}]}
        _, grades = validate_plan(plan, allow_partial=False)
        self.assertEqual(grades[0]["fields"]["学生UID"], "u1")


if __name__ == "__main__":
    unittest.main()
