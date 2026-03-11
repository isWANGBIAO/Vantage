import unittest

from src.utils.action_plan_sanitizer import sanitize_action_plan_markdown


class ActionPlanSanitizerTests(unittest.TestCase):
    def test_preserves_trailing_text_after_inline_corruption_markers(self):
        raw = """* ✅️<b<br>> 固定起床时间，不补觉拖延。
1. ⚠️<b<br>> 今天先确认团队碰头是否同步。
|[21:00]<b<br>> *硬性边界*|<b<br>> **[P0]【开启夜间模式】**<b<br>> •手机电脑台灯切换至夜间模式。
"""

        cleaned = sanitize_action_plan_markdown(raw)

        self.assertIn("固定起床时间，不补觉拖延。", cleaned)
        self.assertIn("今天先确认团队碰头是否同步。", cleaned)
        self.assertIn("手机电脑台灯切换至夜间模式。", cleaned)
        self.assertNotIn("<b<br>>", cleaned)

    def test_removes_inline_b_residue_without_dropping_following_text(self):
        raw = "• 晚间准备：<b<b<b<b<b<bbbbbbbbbbbbb 保留后面的正文。"

        cleaned = sanitize_action_plan_markdown(raw)

        self.assertIn("保留后面的正文。", cleaned)
        self.assertNotIn("bbbbbbbb", cleaned)

    def test_removes_known_corruption_markers(self):
        raw = """### Summary

| Sleep | Keep this content<strong>-</strong><strong>-</strong><strong>-</strong><strong>-</strong><strong>-</strong><strong>-</strong><stron<br>|
| Nutrition | Keep this line too <b<br>> <b<br>> <b<b<b<
### |
* * *
"""

        cleaned = sanitize_action_plan_markdown(raw)

        self.assertIn("### Summary", cleaned)
        self.assertIn("Keep this content", cleaned)
        self.assertNotIn("<strong>-</strong>", cleaned)
        self.assertNotIn("<b<br>>", cleaned)
        self.assertNotIn("### |", cleaned)

    def test_removes_common_html_tags_and_empty_marker_lines(self):
        raw = """| | | |
#### #### #### ####
** ** ** **
<p>Task</p><ul><li>Line one</li></ul>
Value A<br>Value B
"""

        cleaned = sanitize_action_plan_markdown(raw)

        self.assertNotIn("| | | |", cleaned)
        self.assertNotIn("#### ####", cleaned)
        self.assertNotIn("** **", cleaned)
        self.assertNotIn("<p>", cleaned)
        self.assertNotIn("<br>", cleaned)
        self.assertIn("Task - Line one", cleaned)
        self.assertIn("Value A Value B", cleaned)

    def test_preserves_analysis_separator(self):
        raw = "Analysis\n\n---ANALYSIS_END---\n\nPlan"

        cleaned = sanitize_action_plan_markdown(raw)

        self.assertEqual(cleaned.count("---ANALYSIS_END---"), 1)
        self.assertIn("Analysis", cleaned)
        self.assertIn("Plan", cleaned)


if __name__ == "__main__":
    unittest.main()
