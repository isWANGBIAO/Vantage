import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.context import ContextManager


class ContextManagerTests(unittest.TestCase):
    def test_get_messages_keeps_full_history_when_history_exceeds_old_limit(self):
        messages = [
            {"role": "system", "content": "s" * 220},
            {"role": "user", "content": "u" * 59109},
            {"role": "assistant", "content": "a" * 3502},
            {"role": "user", "content": "p" * 1144},
            {"role": "assistant", "content": "r" * 2263},
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            context_file = history_dir / "latest_context.json"
            context_file.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")

            with patch("src.core.context.Config.get_history_dir", return_value=history_dir):
                context_mgr = ContextManager(context_file=str(context_file))

            loaded_messages = context_mgr.get_messages()

        self.assertEqual(loaded_messages, messages)


if __name__ == "__main__":
    unittest.main()
