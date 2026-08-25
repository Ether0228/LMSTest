import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from student_ops.ai import FixtureAIAdapter
from student_ops.course_content_generation import build_course_content_generation_plan


SIX_SECTIONS = """【本节主题】离散随机变量期望值。
【学习内容】
- 离散随机变量取值与概率分布
- 期望值计算步骤
【课堂活动】
教师讲解并组织例题练习。
【课堂任务与评价】
本节无新增任务或评价。
【学习情况与问题】
本节纪要未记录明显共性问题。
【后续安排】
继续练习期望值计算。"""


class CourseContentGenerationTests(unittest.TestCase):
    def test_writes_candidate_but_never_confirms_content(self):
        rows = [{"record_id": "s1", "课程编码": "MDM4U", "内容生成状态": ["待生成"], "内容来源文本": "讲解期望值", "mock_ai_response": SIX_SECTIONS}]
        plan = build_course_content_generation_plan(rows, FixtureAIAdapter())
        fields = plan["session_updates"][0]["fields"]
        self.assertEqual(fields["内容生成状态"], ["已生成"])
        self.assertEqual(fields["内容确认状态"], ["待确认"])
        self.assertIn("本节主题", fields["课程内容结构化结果"])

    def test_missing_source_is_explicit_and_does_not_call_ai(self):
        plan = build_course_content_generation_plan([{"record_id": "s1", "内容生成状态": ["待生成"]}], FixtureAIAdapter())
        self.assertEqual(plan["session_updates"][0]["fields"]["内容生成状态"], ["缺少来源"])


if __name__ == "__main__":
    unittest.main()
