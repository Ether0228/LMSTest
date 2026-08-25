import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.schoology_mapping import build_mapping_write_plan


class SchoologyMappingTests(unittest.TestCase):
    def test_only_manual_stable_ids_become_write_plan(self):
        plan = build_mapping_write_plan(
            [{"record_id": "student1", "Schoology学生UID": "101"}],
            [{"record_id": "task1", "SchoologySectionNID": "201", "Schoology作业NID": "301"}],
        )
        self.assertEqual(plan["student_updates"][0]["fields"]["Schoology学生UID"], "101")
        self.assertEqual(plan["course_task_updates"][0]["fields"]["Schoology作业NID"], "301")
        self.assertFalse(plan["exceptions"])

    def test_duplicate_or_partial_mappings_are_rejected(self):
        plan = build_mapping_write_plan(
            [{"record_id": "a", "Schoology学生UID": "101"}, {"record_id": "b", "Schoology学生UID": "101"}],
            [{"record_id": "task1", "SchoologySectionNID": "201", "Schoology作业NID": ""}],
        )
        self.assertEqual(len(plan["exceptions"]), 2)


if __name__ == "__main__":
    unittest.main()
