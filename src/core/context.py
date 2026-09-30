"""Shared conversation persistence with atomic, revision-checked writes."""
import hashlib
import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.core.config import Config

_locks_guard = threading.Lock()
_locks = {}
_held = threading.local()


class ContextConflictError(RuntimeError):
    """A reset or new plan superseded the context used by a model request."""


class ContextReadError(RuntimeError):
    """Existing context cannot be read safely; never replace it with empty state."""


@contextmanager
def context_transaction(path):
    """Short directory-wide process/thread lock; never hold across model calls."""
    directory = Path(path).resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    key = str(directory)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_held, "directories", None)
        if held is None:
            held = _held.directories = set()
        if key in held:
            yield
            return
        with (directory / ".context.lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if not handle.tell():
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _bytes(path):
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return b""


def _revision_path(path):
    # Shared by live/base context files: a partial plan-context refresh must also
    # invalidate a chat that loaded the previous base, even if latest was locked.
    return Path(path).parent / ".context.revision"


def context_revision(path):
    return hashlib.sha256(_bytes(path) + b"\0" + _bytes(_revision_path(path))).hexdigest()


def _atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write_json(path, payload):
    with context_transaction(path):
        _atomic_bytes(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def read_context_snapshot(path):
    try:
        with context_transaction(path):
            try:
                raw = Path(path).read_bytes()
            except FileNotFoundError:
                return [], context_revision(path)
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ContextReadError("Conversation context is unreadable; original files were preserved.") from None
            if not isinstance(payload, list):
                raise ContextReadError("Conversation context has an invalid format; original files were preserved.")
            return payload, context_revision(path)
    except OSError:
        raise ContextReadError("Conversation context could not be read; original files were preserved.") from None


def write_context_messages(path, messages, *, expected_revision=None):
    with context_transaction(path):
        if expected_revision is not None and context_revision(path) != expected_revision:
            raise ContextConflictError("Conversation changed during generation; retry with the current context.")
        atomic_write_json(path, messages)
        # Reset invalidates in-flight requests even when the JSON is unchanged.
        _atomic_bytes(_revision_path(path), uuid.uuid4().hex.encode("ascii"))
        return context_revision(path)


def replace_context_file(source, target):
    with context_transaction(target):
        os.replace(source, target)
        if not str(target).endswith("_session.json"):
            _atomic_bytes(_revision_path(target), uuid.uuid4().hex.encode("ascii"))


class ContextManager:
    def __init__(self, context_file=None):
        self.history_dir = Config.get_history_dir()
        self.context_file = Path(context_file) if context_file else self.history_dir / "latest_context.json"
        self.messages = []
        self.load()

    def load(self):
        self.messages, self.revision = read_context_snapshot(self.context_file)

    def save(self):
        self.revision = write_context_messages(
            self.context_file, self.messages, expected_revision=self.revision,
        )

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})

    @property
    def token_count(self):
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        return total_chars // 3

    def get_messages(self, prune=True):
        import copy
        return copy.deepcopy(self.messages)

    def clear(self):
        self.messages = self.messages[:1] if self.messages and self.messages[0].get("role") == "system" else []
        self.save()
