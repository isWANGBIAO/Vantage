"""Draft policy plus the actual send_chat method, without a display dependency."""
import ast
from pathlib import Path
import sys
import threading
import types
import unittest

LINUX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LINUX))
from vantage_linux.chat_draft import ChatDraftAttempt
from vantage_linux.client import ClientError, payload_text


class ChatDraftPolicyTests(unittest.TestCase):
    def test_restore_only_when_version_known_unchanged_and_composer_empty(self):
        attempt = ChatDraftAttempt('  original draft\n', 'before', 0)
        self.assertEqual(attempt.recover({'context_version': 'before'}, '', clear_epoch=0), '  original draft\n')
        for context, text, epoch, same in [
            ({'context_version': 'after'}, '', 0, True),
            ({'context_version': 'before'}, 'new draft', 0, True),
            ({'context_version': 'before'}, ' ', 0, True),
            ({'context_version': 'before'}, '', 1, True),
            ({'context_version': 'before'}, '', 0, False),
            ({}, '', 0, True),
            (None, '', 0, True),
        ]:
            with self.subTest(context=context, text=text, epoch=epoch, same=same):
                self.assertIsNone(attempt.recover(context, text, clear_epoch=epoch, same_attempt=same))
        self.assertIsNone(ChatDraftAttempt('draft', None, 0).recover({'context_version': None}, '', clear_epoch=0))


class FakeText:
    def __init__(self, text=''):
        self.text = text
    def get_buffer(self):
        return self
    def set_text(self, text):
        self.text = text


def actual_send_method():
    # Execute the exact production method with lightweight native-widget seams.
    # The CI GTK smoke separately exercises actual widgets and rendering.
    tree = ast.parse((LINUX / 'vantage_linux/application.py').read_text(encoding='utf-8'))
    window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Window')
    method = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == 'send_chat')
    namespace = {
        'threading': threading, 'ClientError': ClientError, 'ChatDraftAttempt': ChatDraftAttempt,
        'payload_text': payload_text, 'buffer_text': lambda view: view.text,
        'set_view_text': lambda view, text: view.set_text(text),
        'GLib': types.SimpleNamespace(idle_add=lambda callback: callback()),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'production-send_chat', 'exec'), namespace)
    return namespace['send_chat']


class ChatSendFailureTests(unittest.TestCase):
    def run_failure(self, returned_version='before', new_draft='', clear=False, read_failure=False):
        requests = []
        fake = types.SimpleNamespace(
            pending=set(), chat_input=FakeText('  must survive transport failure\n'), chat_stop=None,
            chat_context_version='before', chat_clear_epoch=0, chat_text='previous', page='chat',
            chat_options=lambda: {}, tr=lambda zh, en: en, notice_ok=lambda text: None,
            errors=[], reloads=0,
        )
        fake.show_error = fake.errors.append
        fake.load_chat = lambda: setattr(fake, 'reloads', fake.reloads + 1)
        def request(path):
            requests.append(('GET', path))
            if read_failure:
                raise ClientError('Offline during recovery')
            return {'context_version': returned_version, 'messages': []}
        def stream(path, method, body, stop):
            requests.append((method, path))
            fake.chat_input.text = new_draft
            if clear:
                fake.chat_clear_epoch += 1
            raise ClientError('Backend returned HTTP 503', 503)
            yield  # Keep the production lazy-generator failure point.
        fake.client = types.SimpleNamespace(request=request, stream=stream)
        def run_async(key, worker, done=None, on_error=None):
            fake.pending.add(key)
            try:
                value = worker()
            except Exception as exc:
                fake.pending.discard(key)
                if on_error:
                    on_error(exc)
            else:
                fake.pending.discard(key)
                if done:
                    done(value)
            return True
        fake.run_async = run_async
        actual_send_method()(fake)
        self.assertEqual(requests, [('POST', '/api/v1/chat'), ('GET', '/api/v1/chat/context')])
        self.assertEqual(len(fake.errors), 1)
        return fake

    def test_pre_event_http_failure_restores_original_exact_text(self):
        fake = self.run_failure()
        self.assertEqual(fake.chat_input.text, '  must survive transport failure\n')
        self.assertEqual(fake.reloads, 1)

    def test_committed_or_revised_context_does_not_restore_or_resend(self):
        self.assertEqual(self.run_failure(returned_version='after').chat_input.text, '')

    def test_new_draft_is_not_overwritten(self):
        self.assertEqual(self.run_failure(new_draft='new draft').chat_input.text, 'new draft')

    def test_clear_intent_blocks_late_recovery(self):
        self.assertEqual(self.run_failure(clear=True).chat_input.text, '')

    def test_unavailable_authoritative_read_does_not_guess(self):
        fake = self.run_failure(read_failure=True)
        self.assertEqual(fake.chat_input.text, '')
        self.assertEqual(fake.failed_chat_attempt[0].text, '  must survive transport failure\n')
        self.assertEqual(fake.failed_chat_attempt[0].recover({'context_version': 'before'}, '', clear_epoch=0), '  must survive transport failure\n')


if __name__ == '__main__':
    unittest.main()
