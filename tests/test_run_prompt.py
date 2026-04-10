import unittest

from src.scripts import run_prompt


class RunPromptTests(unittest.TestCase):
    def test_format_chat_message_with_timestamp_prefixes_sent_time(self):
        formatted = run_prompt.format_chat_message_with_timestamp(
            "现在什么时侯",
            "2026-04-08T12:02:03+08:00",
        )

        self.assertIn("Message timestamp: 2026-04-08 12:02:03+08:00", formatted)
        self.assertTrue(formatted.endswith("现在什么时侯"))

    def test_format_chat_message_with_timestamp_returns_original_message_without_timestamp(self):
        formatted = run_prompt.format_chat_message_with_timestamp(
            "现在什么时侯",
            None,
        )

        self.assertEqual(formatted, "现在什么时侯")


if __name__ == "__main__":
    unittest.main()
