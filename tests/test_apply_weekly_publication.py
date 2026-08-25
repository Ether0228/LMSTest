import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from apply_weekly_publication import validate_publication


class ApplyPublicationTests(unittest.TestCase):
    def test_only_matching_confirmed_feedback_can_be_published(self):
        manifest = {"反馈唯一键": "term:第1周", "publication_fields": {"发布版本": "v1", "发布时间": "2026-09-08 18:00", "网页链接": "https://x", "PDF链接": "https://x.pdf"}}
        fields = validate_publication({"反馈唯一键": "term:第1周", "反馈状态": ["已确认"]}, manifest)
        self.assertEqual(fields["发布版本"], "v1")
        with self.assertRaisesRegex(RuntimeError, "not_confirmed"):
            validate_publication({"反馈唯一键": "term:第1周", "反馈状态": ["草稿"]}, manifest)
        with self.assertRaisesRegex(RuntimeError, "already_published"):
            validate_publication({"反馈唯一键": "term:第1周", "反馈状态": ["已发布"]}, manifest)
        with self.assertRaisesRegex(RuntimeError, "key_mismatch"):
            validate_publication({"反馈唯一键": "other", "反馈状态": ["已确认"]}, manifest)

    def test_rejects_manifest_missing_a_versioned_publication_field(self):
        manifest = {"反馈唯一键": "term:第1周", "publication_fields": {"发布版本": "v1", "网页链接": "https://x", "PDF链接": "https://x.pdf"}}
        with self.assertRaisesRegex(RuntimeError, "manifest_incomplete"):
            validate_publication({"反馈唯一键": "term:第1周", "反馈状态": ["已确认"]}, manifest)


if __name__ == "__main__":
    unittest.main()
