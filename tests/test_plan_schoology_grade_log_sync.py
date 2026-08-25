import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from plan_schoology_grade_log_sync import build_bulk_plan


class SchoologyGradeLogSyncPlanTests(unittest.TestCase):
    def test_only_selected_term_with_stable_uid_can_produce_grade_log(self):
        snapshot = {"grade_items": [{"grade_item_key": "s1:a1", "grade_item_nid": "a1"}], "grade_records": [{"student_uid": "u1", "section_nid": "s1", "grade_item_key": "s1:a1", "score": 90, "max_points": 100, "observed_at": "2026-09-05"}]}
        result = build_bulk_plan(
            snapshot=snapshot,
            selected_terms=[{"record_id": "term1", "Schoology学生UID": "u1"}, {"record_id": "term2", "Schoology学生UID": ""}],
            course_tasks=[{"record_id": "ct1", "SchoologySectionNID": "s1", "Schoology作业NID": "a1"}],
            student_tasks=[{"record_id": "st1", "任务归属学生": [{"id": "term1"}], "所属课程任务": [{"id": "ct1"}]}],
            grade_records=[],
        )
        self.assertEqual(len(result["grade_updates"]), 1)
        self.assertIn("首次同步", result["grade_updates"][0]["fields"]["分数变化日志"])
        self.assertEqual(result["skipped"][0]["类型"], "缺少Schoology学生UID")

    def test_refuses_uid_shared_by_two_selected_terms(self):
        result = build_bulk_plan(snapshot={}, selected_terms=[{"record_id": "term1", "Schoology学生UID": "u1"}, {"record_id": "term2", "Schoology学生UID": "u1"}], course_tasks=[], student_tasks=[], grade_records=[])
        self.assertEqual(len(result["exceptions"]), 2)
        self.assertEqual(result["grade_updates"], [])
