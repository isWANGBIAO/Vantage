import asyncio
import json
import os
import sys
import unittest

from src.utils.action_plan_stream import (
    build_action_plan_stream_printer,
    emit_action_plan_stream_event,
)


class ActionPlanStreamPrinterTests(unittest.TestCase):
    def test_unicode_and_escaped_text_survives_real_default_limit_pipe(self):
        for text in ("中" * 12000, "🙂" * 12000, ('中文🙂\\\"\n\t' * 12000)):
            with self.subTest(sample=text[:8]):
                async def read_pipe(text=text):
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, "-c",
                        "import sys; from src.utils.action_plan_stream import emit_action_plan_stream_event; "
                        "emit_action_plan_stream_event('analysis', 'prompt', sys.stdin.read())",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    )
                    proc.stdin.write(text.encode("utf-8"))
                    await proc.stdin.drain()
                    proc.stdin.close()
                    try:
                        lines = []
                        while line := await proc.stdout.readline():
                            self.assertLess(len(line), 65536)
                            lines.append(line)
                        self.assertEqual(await proc.wait(), 0)
                        return lines
                    finally:
                        if proc.returncode is None:
                            proc.kill()
                            await proc.wait()

                lines = asyncio.run(read_pipe())
                self.assertEqual(
                    "".join(json.loads(line.decode("utf-8").split(":", 1)[1]) for line in lines),
                    text,
                )

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

    def test_emits_section_prefixed_start_events(self):
        emitted = []

        emit_action_plan_stream_event("analysis", "start", "", emit=emitted.append)

        self.assertEqual(
            emitted,
            ['STREAM_ANALYSIS_START:""'],
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

    def test_emits_section_prefixed_metadata_events_with_json_payload(self):
        emitted = []

        emit_action_plan_stream_event(
            "plan",
            "metadata",
            {
                "model": "secondary-chat-model",
                "provider_route": "cliproxyapi_secondary",
            },
            emit=emitted.append,
        )

        self.assertEqual(len(emitted), 1)
        prefix = "STATS_JSON:"
        self.assertTrue(emitted[0].startswith(prefix))
        self.assertEqual(
            json.loads(emitted[0][len(prefix):]),
            {
                "model": "secondary-chat-model",
                "provider_route": "cliproxyapi_secondary",
            },
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
