import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.schoology_adapter import build_schoology_write_plan


class SchoologyAdapterTests(unittest.TestCase):
    def test_maps_only_stable_student_course_assignment_identity(self):
        snapshot = {
            "submission_events": [{"student_uid": "u1", "section_nid": "s1", "schoology_id": "a1", "status": "submitted", "submitted_at": "2026-09-04T12:00:00+08:00"}],
            "grade_items": [{"grade_item_key": "s1:a1", "grade_item_nid": "a1"}],
            "grade_records": [{"student_uid": "u1", "section_nid": "s1", "grade_item_key": "s1:a1", "score": 80, "max_points": 100, "pct": 80, "comment_text": "有清晰步骤", "overall_course_grade": 82, "observed_at": "2026-09-04T12:05:00+08:00"}],
        }
        course_tasks = [{"record_id": "course_task_1", "SchoologySectionNID": "s1", "Schoology作业NID": "a1"}]
        student_tasks = [{"record_id": "student_task_1", "任务归属学生": [{"id": "term_1"}], "所属课程任务": [{"id": "course_task_1"}]}]
        plan = build_schoology_write_plan(snapshot, student_uid="u1", student_term_id="term_1", course_task_records=course_tasks, student_task_records=student_tasks, grade_records=[])
        self.assertEqual(plan["student_task_updates"][0]["record_id"], "student_task_1")
        self.assertEqual(plan["student_task_updates"][0]["fields"]["当前提交状态"], ["已提交"])
        self.assertEqual(plan["grade_updates"][0]["fields"]["得分"], 80)
        self.assertEqual(plan["course_grade_observations"][0]["overall"], 82)
        self.assertFalse(plan["exceptions"])

    def test_never_falls_back_to_name_when_task_mapping_is_missing(self):
        snapshot = {"submission_events": [{"student_uid": "u1", "section_nid": "s1", "schoology_id": "unknown", "status": "submitted"}], "grade_records": []}
        plan = build_schoology_write_plan(snapshot, student_uid="u1", student_term_id="term_1", course_task_records=[], student_task_records=[], grade_records=[])
        self.assertEqual(plan["student_task_updates"], [])
        self.assertEqual(plan["exceptions"][0]["类型"], "未匹配课程任务")


if __name__ == "__main__":
    unittest.main()
