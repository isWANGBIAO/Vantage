import copy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src/native/linux'))
sys.path.insert(0, str(ROOT))
from vantage_linux.client import Client, ClientError, JobObserver, backend_url, complete_result, provider_patch
from vantage_linux.chart_data import prepare_chart, normalized_y
from src.native.testing.fixture_backend import start_fixture, TODAY


class NativeClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_fixture()
        cls.client = Client(f'http://127.0.0.1:{cls.server.server_address[1]}')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        from src.native.testing.fixture_backend import state
        self.server.state = state()

    def test_loopback_validation(self):
        for value in ('http://example.com', 'http://127.0.0.1@evil.test', 'http://localhost?secret=a', 'file:///tmp/a', 'http://127.0.0.1\\@evil.test', 'http://127.0.0.1:0', 'http://127.0.0.1\n'):
            with self.subTest(value=value), self.assertRaises(ClientError):
                backend_url(value)
        self.assertEqual(backend_url('https://[::1]:8080/proxy/'), 'https://[::1]:8080/proxy')
        self.assertEqual(backend_url(env={'VANTAGE_BACKEND_HOST': '::1', 'VANTAGE_BACKEND_PORT': '8123'}), 'http://[::1]:8123')

    def test_traversal_and_absolute_resources_rejected(self):
        for path in ('https://evil.test', '/api/v1/../secret', '/api/v1/%2e%2e/secret', '//evil.test', '/static/other/test'):
            with self.assertRaises(ClientError):
                self.client.request(path)

    def test_provider_patch_preserves_all_routes_and_omits_keys(self):
        state = {'provider': {'providers': {'one': {'api_key': '********', 'model': 'a'}, 'two': {'api_key': '********', 'model': 'b'}}}}
        patch = provider_patch(state, 'one', {'base_url': 'http://localhost:12/v1'})
        self.assertEqual(set(patch['provider_config']['providers']), {'one', 'two'})
        self.assertNotIn('api_key', patch['provider_config']['providers']['one'])
        self.assertEqual(state['provider']['providers']['one']['api_key'], '********')
        self.assertEqual(provider_patch(state, 'two', {}, clear_key=True)['provider_config']['providers']['two']['api_key'], '')

    def test_complete_result_is_strict(self):
        self.assertTrue(complete_result(TODAY))
        for body in (None, 1, {}, [], '', '  '):
            bad = copy.deepcopy(TODAY)
            bad['plan']['body'] = body
            self.assertFalse(complete_result(bad))
        self.assertFalse(complete_result({**TODAY, 'error': 'failed'}))

    def observe(self, mode):
        self.server.state['job_mode'] = mode
        job = self.client.request('/api/v1/action-plan/jobs', 'POST', {})
        events = []
        observer = JobObserver(self.client, job['id'])
        observer.run(lambda kind, data: events.append((kind, data)))
        return events

    def test_job_success_reconnect_truncate_failure_cancel(self):
        for mode in ('success', 'disconnect', 'truncated', 'failed', 'cancelled'):
            with self.subTest(mode=mode):
                self.setUp()
                events = self.observe(mode)
                self.assertEqual(any(k == 'result' for k, _ in events), mode not in {'failed', 'cancelled'})
                if mode == 'truncated':
                    self.assertTrue(any(k == 'truncated' for k, _ in events))
                if mode == 'disconnect':
                    seqs = [v['sequence'] for k, v in events if k == 'event']
                    self.assertEqual(len(seqs), len(set(seqs)))

    def test_cancel_is_explicit(self):
        job = self.client.request('/api/v1/action-plan/jobs', 'POST', {})
        observer = JobObserver(self.client, job['id'])
        observer.stop.set()
        observer.run(lambda *_: self.fail('Stopped observer emitted'))
        self.assertEqual(self.client.request('/api/v1/action-plan/jobs/' + job['id'])['status'], 'running')
        self.assertEqual(self.client.request('/api/v1/action-plan/jobs/' + job['id'] + '/cancel', 'POST', {})['status'], 'cancelled')

    def test_chat_context_clear_is_authoritative(self):
        list(self.client.stream('/api/v1/chat', 'POST', {'message': 'Synthetic message'}))
        before = self.client.request('/api/v1/chat/context')
        after = self.client.request('/api/v1/chat/context', 'DELETE')
        self.assertGreater(len(before['messages']), len(after['messages']))
        self.assertEqual(after['messages'], after['display_messages'])
        self.assertTrue(after['has_action_plan_context'])

    def test_chart_time_axes_stacks_gaps_and_inverse(self):
        chart = prepare_chart({'xAxis': {'type': 'time'}, 'yAxis': [{'min': 0, 'max': 100}, {'min': 0, 'max': 10, 'inverse': True}], 'series': [
            {'type': 'bar', 'stack': 'a', 'data': [['2026-01-01', 10], ['2026-01-03', 20], ['2026-01-10', None]]},
            {'type': 'bar', 'stack': 'a', 'data': [['2026-01-01', 5], ['2026-01-03', 4], ['2026-01-10', 3]]},
            {'type': 'line', 'yAxisIndex': 1, 'data': [['2026-01-01', 5], ['2026-01-03', 7]]},
        ]})
        self.assertEqual(chart['series'][1]['coordinates'][0]['base'], 10)
        self.assertEqual(chart['series'][1]['coordinates'][0]['y'], 15)
        self.assertIsNone(chart['series'][0]['coordinates'][2]['y'])
        self.assertEqual(len(chart['bar_groups']), 1)
        points = chart['series'][0]['coordinates']
        self.assertAlmostEqual((points[1]['x']-points[0]['x'])/(points[2]['x']-points[0]['x']), 2/9)
        self.assertEqual(normalized_y(2, chart['axes'][1]), .2)
        self.assertEqual(normalized_y(20, chart['axes'][0]), .8)

    def test_owned_backend_defaults_match_canonical_data_root(self):
        from vantage_linux.lifecycle import BackendHost
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'XDG_DATA_HOME': '/ignored'}, clear=True):
            host = BackendHost(self.client)
            self.assertEqual(host.data_dir, Path.home() / '.local/share/Vantage')
        self.assertIsNone(host.process)
        host.close()


if __name__ == '__main__':
    unittest.main()
