import unittest

from src.utils.action_plan_stream import (
    build_action_plan_stream_printer,
    emit_action_plan_stream_event,
)


class ActionPlanStreamPrinterTests(unittest.TestCase):
    def test_chunks_large_prompt_events_to_multiple_lines(self):
        emitted = []
        long_prompt = "A" * 40000

        emit_action_plan_stream_event(
            "analysis",
            "prompt",
            long_prompt,
            emit=emitted.append,
        )

        self.assertGreater(len(emitted), 1)
        self.assertTrue(all(line.startswith('STREAM_ANALYSIS_PROMPT:') for line in emitted))

    def test_emits_section_prefixed_system_events(self):
        emitted = []

        emit_action_plan_stream_event("analysis", "system", "System body", emit=emitted.append)

        self.assertEqual(
            emitted,
            ['STREAM_ANALYSIS_SYSTEM:"System body"'],
        )

    def test_emits_section_prefixed_prompt_events(self):
        emitted = []

        emit_action_plan_stream_event("analysis", "prompt", "Prompt body", emit=emitted.append)

        self.assertEqual(
            emitted,
            ['STREAM_ANALYSIS_PROMPT:"Prompt body"'],
        )

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
