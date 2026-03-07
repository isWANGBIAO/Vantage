import unittest

from src.utils.action_plan_sanitizer import sanitize_action_plan_markdown


class ActionPlanSanitizerTests(unittest.TestCase):
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
