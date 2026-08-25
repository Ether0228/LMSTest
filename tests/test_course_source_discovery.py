import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.course_source_discovery import discover_smart_minutes, docx_links


class CourseSourceDiscoveryTests(unittest.TestCase):
    def test_only_docx_links_are_discovered_and_deduplicated(self):
        links = docx_links("见 https://a.feishu.cn/docx/ABC_123?x=1 和 https://a.feishu.cn/wiki/ignored ；再发 https://a.feishu.cn/docx/ABC_123")
        self.assertEqual(links, [("https://a.feishu.cn/docx/ABC_123?x=1", "ABC_123")])

    def test_discovery_requires_registered_enabled_chat_and_keeps_ledger(self):
        registry = [{"学期": "S6", "课程编码": "MHF4U", "教师": "Taylor", "chat_id": "oc_course", "启用": True}]
        messages = [
            {"chat_id": "oc_course", "message_id": "om_1", "create_time": "2026-09-02T10:00:00+08:00", "content": "https://a.feishu.cn/docx/DocToken", "deleted": False},
            {"chat_id": "oc_other", "message_id": "om_2", "content": "https://a.feishu.cn/docx/Other", "deleted": False},
            {"chat_id": "oc_course", "message_id": "om_3", "content": "https://a.feishu.cn/docx/Deleted", "deleted": True},
        ]
        rows = discover_smart_minutes(messages, registry)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["课程编码"], "MHF4U")
        self.assertEqual(rows[0]["文档token"], "DocToken")
        self.assertEqual(rows[0]["来源状态"], "待场次匹配")


if __name__ == "__main__":
    unittest.main()
