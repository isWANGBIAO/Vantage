"""Conservative recovery of an uncommitted chat draft after a transport error."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatDraftAttempt:
    text: str
    context_version: str | None
    clear_epoch: int

    def recover(self, authoritative_context, current_input, *, clear_epoch, same_attempt=True):
        """Return text only after the backend proves the context is unchanged.

        Never resend here, replace a newer composer draft, revive a draft after
        Clear, or treat two unknown context versions as proof of no commit.
        """
        if (
            not same_attempt
            or clear_epoch != self.clear_epoch
            or current_input != ""
            or not isinstance(self.context_version, str)
            or not self.context_version
            or not isinstance(authoritative_context, dict)
            or authoritative_context.get("context_version") != self.context_version
        ):
            return None
        return self.text
