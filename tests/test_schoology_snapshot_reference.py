import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.schoology_snapshot_reference import build_snapshot_references


class SchoologySnapshotReferenceTests(unittest.TestCase):
    def test_exports_only_existing_stable_ids_without_name_matching(self):
        reference = build_snapshot_references({
            "course_sections": [{"section_nid": "201", "course_code": "MHF4U"}],
            "section_enrollments": [{"student_uid": "101", "student_name": "学生甲", "section_nid": "201", "role": "student"}],
            "grade_items": [{"section_nid": "201", "grade_item_nid": "301", "title": "U1 Quiz", "max_points": 10, "due_at": "2026-08-25", "category_title": "Quiz"}],
        })
        self.assertEqual(reference["enrollments"][0]["Schoology学生UID"], "101")
        self.assertEqual(reference["course_tasks"][0]["Schoology作业NID"], "301")
        self.assertEqual(reference["course_tasks"][0]["课程代码"], "MHF4U")

    def test_normalizes_explicit_olc_schoology_title(self):
        reference = build_snapshot_references({
            "course_sections": [{"section_nid": "201", "course_code": "G12 Ontario Secondary School Literacy"}],
            "grade_items": [{"section_nid": "201", "grade_item_nid": "301", "title": "U1 Quiz"}],
        })
        self.assertEqual(reference["course_tasks"][0]["课程代码"], "OLC4O")
