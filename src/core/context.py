import json
import logging
from pathlib import Path
from datetime import datetime
from src.core.config import Config

class ContextManager:
    def __init__(self, context_file=None, token_limit=12000):
        self.history_dir = Config.get_history_dir()
        self.context_file = Path(context_file) if context_file else self.history_dir / "latest_context.json"
        self.token_limit = token_limit
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
            logging.info(f"Context saved to: {self.context_file}")
        except Exception as e:
            logging.error(f"Warning: Failed to save context: {e}")

    def add_message(self, role, content):
        """Add a message to the context."""
        self.messages.append({"role": role, "content": content})

    def get_messages(self, prune=True):
        """
        Get messages, optionally pruning to fit within token limit.
        Strategy:
        1. Always keep the System Prompt (if present at index 0).
        2. Keep the most recent messages that fit within the limit.
        """
        if not prune:
            return self.messages

        if not self.messages:
            return []

        # Simple tokenizer approximation (1 token ~= 4 chars for English, 
        # but for mixed/Chinese, it varies. Conservative: 1.5 chars/token? 
        # OpenAI official is ~0.75 words/token. 
        # Let's say 1 token = 3 chars as a safe average for mixed content)
        CHAR_PER_TOKEN = 3 

        current_tokens = 0
        pruned_messages = []
        
        # Identify System Prompt
        system_message = None
        start_index = 0
        if self.messages and self.messages[0].get("role") == "system":
            system_message = self.messages[0]
            current_tokens += len(system_message.get("content", "")) / CHAR_PER_TOKEN
            start_index = 1
        
        # Iterate backwards from the end
        temp_messages = []
        for i in range(len(self.messages) - 1, start_index - 1, -1):
            msg = self.messages[i]
            content = msg.get("content", "")
            est_tokens = len(content) / CHAR_PER_TOKEN + 10 # +10 for metadata overhead
            
            if current_tokens + est_tokens > self.token_limit:
                break
            
            current_tokens += est_tokens
            temp_messages.append(msg)
        
        # Reconstruct
        if system_message:
            pruned_messages.append(system_message)
        
        pruned_messages.extend(reversed(temp_messages))
        
        return pruned_messages

    def clear(self):
        """Clear context but keep system prompt if it exists"""
        if self.messages and self.messages[0].get("role") == "system":
            self.messages = [self.messages[0]]
        else:
            self.messages = []
        self.save()
