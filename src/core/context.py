import json
import logging
from pathlib import Path
from datetime import datetime
from src.core.config import Config

class ContextManager:
    def __init__(self, context_file=None):
        self.history_dir = Config.get_history_dir()
        self.context_file = Path(context_file) if context_file else self.history_dir / "latest_context.json"
        self.messages = []
        self.load()

    def load(self):
        """Load conversation context from file."""
        if self.context_file.exists():
            try:
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except Exception as e:
                logging.warning(f"Failed to load context: {e}")
                self.messages = []
        else:
            self.messages = []

    def save(self):
        """Save conversation context to file."""
        try:
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
            logging.debug(f"Context saved to: {self.context_file}")
        except Exception as e:
            logging.error(f"Warning: Failed to save context: {e}")

    def add_message(self, role, content):
        """Add a message to the context."""
        self.messages.append({"role": role, "content": content})

    @property
    def token_count(self):
        """Estimate token count."""
        # Simple estimation: 1 token ~= 4 chars (English) or 2-3 chars (Chinese)
        # We'll use a safer estimation of 3 chars per token
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        return total_chars // 3

    def get_messages(self, prune=True):
        """
        Get messages as deep copies to prevent external mutation.
        Returns deep copies to prevent external mutation of internal state.
        """
        import copy

        return copy.deepcopy(self.messages)

    def clear(self):
        """Clear context but keep system prompt if it exists"""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []
        self.save()
