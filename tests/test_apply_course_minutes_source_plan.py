import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from apply_course_minutes_source_plan import validate_plan


class ApplyCourseMinutesSourcePlanTests(unittest.TestCase):
    def test_exceptions_require_explicit_partial_authorization(self):
        plan = {"session_updates": [{"record_id": "s1", "fields": {"内容来源链接": "https://x"}}], "exceptions": [{"类型": "待补实际上课日期"}]}
        with self.assertRaisesRegex(RuntimeError, "course_source_plan_contains_exceptions"):
            validate_plan(plan, allow_partial=False)
        self.assertEqual(len(validate_plan(plan, allow_partial=True)), 1)


if __name__ == "__main__":
    unittest.main()
