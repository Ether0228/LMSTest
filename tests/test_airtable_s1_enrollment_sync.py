import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from sync_airtable_s1_enrollment import build_source_enrolment, session_candidates


class AirtableS1EnrolmentSyncTests(unittest.TestCase):
    def test_builds_two_slot_enrolment_by_oen_and_maps_campus(self):
        students = [{"id": "at-student", "fields": {"Names ONLY": "Student A", "OEN": "111", "Campus": ["上外"]}}]
        rows = [
            {"id": "s1a", "fields": {"Name": "S1-ENG4U-N", "Student Name": ["at-student"], "Period (bejing)": ["T1(8-10am)"]}},
            {"id": "s1b", "fields": {"Name": "S1-MHF4U-N", "Student Name": ["at-student"], "Period (bejing)": ["T2(10-12noon)"]}},
        ]
        enrolment, exceptions = build_source_enrolment(
            airtable_students=students, s1_rows=rows,
            name_field="Names ONLY", oen_field="OEN", campus_field="Campus",
            s1_name_field="Name", s1_students_field="Student Name", period_field="Period (bejing)",
        )
        self.assertEqual(exceptions, [])
        self.assertEqual(enrolment["111"], {"name": "Student A", "oen": "111", "campus": "上海", "T1": "ENG4U", "T2": "MHF4U"})

    def test_refuses_two_courses_in_one_slot(self):
        students = [{"id": "at-student", "fields": {"Names ONLY": "Student A", "OEN": "111", "Campus": ["北京"]}}]
        rows = [
            {"id": "a", "fields": {"Name": "S1-ENG4U-N", "Student Name": ["at-student"], "Period (bejing)": ["T1(8-10am)"]}},
            {"id": "b", "fields": {"Name": "S1-ENG3U-N", "Student Name": ["at-student"], "Period (bejing)": ["T1(8-10am)"]}},
        ]
        _, exceptions = build_source_enrolment(
            airtable_students=students, s1_rows=rows,
            name_field="Names ONLY", oen_field="OEN", campus_field="Campus",
            s1_name_field="Name", s1_students_field="Student Name", period_field="Period (bejing)",
        )
        self.assertEqual(exceptions[0]["类型"], "同一学生同一时段多门课程")

    def test_session_candidates_respect_course_and_group(self):
        term = {"semester_id": "sem", "T1": "ENG4U", "T2": "MHF4U", "T1分组": "A组", "T2分组": None}
        sessions = [
            {"record_id": "big", "学期": [{"id": "sem"}], "课程编码": ["ENG4U"], "教学覆盖学生": ["大班课"]},
            {"record_id": "group-a", "学期": [{"id": "sem"}], "课程编码": ["ENG4U"], "教学覆盖学生": ["A组"]},
            {"record_id": "group-b", "学期": [{"id": "sem"}], "课程编码": ["ENG4U"], "教学覆盖学生": ["B组"]},
            {"record_id": "t2-group", "学期": [{"id": "sem"}], "课程编码": ["MHF4U"], "教学覆盖学生": ["A组"]},
        ]
        self.assertEqual([row["record_id"] for row in session_candidates(term, sessions)], ["big", "group-a"])


if __name__ == "__main__":
    unittest.main()
