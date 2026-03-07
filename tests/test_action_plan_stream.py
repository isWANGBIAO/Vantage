import unittest

from src.utils.action_plan_stream import build_action_plan_stream_printer


class ActionPlanStreamPrinterTests(unittest.TestCase):
    def test_emits_section_prefixed_content_events(self):
        emitted = []
        callback = build_action_plan_stream_printer("plan", emit=emitted.append)

        callback("content", "# Today's Action Plan")

        self.assertEqual(
            emitted,
            ['STREAM_PLAN_CONTENT:"# Today\'s Action Plan"'],
        )

    def test_emits_section_prefixed_thinking_events(self):
        emitted = []
        callback = build_action_plan_stream_printer("analysis", emit=emitted.append)

        callback("thinking", "Analyzing")

        self.assertEqual(
            emitted,
            ['STREAM_ANALYSIS_THINKING:"Analyzing"'],
        )

    def test_rejects_unknown_sections(self):
        with self.assertRaises(ValueError):
            build_action_plan_stream_printer("chat")
