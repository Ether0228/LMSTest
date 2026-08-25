import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from sync_weekly_feedback_base import rows_from_matrix


class WeeklyFeedbackSyncTests(unittest.TestCase):
    def test_matrix_rows_preserve_record_id_and_field_names(self):
        response = {"data": {"fields": ["反馈唯一键", "反馈状态"], "record_id_list": ["rec_1"], "data": [["term_1:第1周", ["草稿"]]]}}
        self.assertEqual(rows_from_matrix(response), [{"record_id": "rec_1", "反馈唯一键": "term_1:第1周", "反馈状态": ["草稿"]}])


if __name__ == "__main__":
    unittest.main()
