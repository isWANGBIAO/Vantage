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

class ResultValidationTests(unittest.TestCase):
    def run_result(self, snapshot, today=TODAY):
        class Stub:
            def request(self, path):
                return copy.deepcopy(today if path.endswith('/today') else snapshot)
        output = []
        JobObserver(Stub(), 'job').run(lambda kind, value: output.append((kind, value)))
        return [kind for kind, _ in output]

    def test_failed_saved_result_is_not_success(self):
        for result in ({}, {**TODAY, 'error': 'failed'}, {**TODAY, 'plan': {'body': None}}):
            with self.subTest(result=result):
                kinds = self.run_result({'id': 'job', 'status': 'succeeded', 'result': result})
                self.assertIn('invalid_result', kinds)
                self.assertNotIn('result', kinds)

    def test_stale_today_is_not_job_success(self):
        kinds = self.run_result({'id': 'job', 'status': 'succeeded', 'result': {**TODAY, 'id': 'new-plan'}}, TODAY)
        self.assertIn('invalid_result', kinds)
        self.assertNotIn('result', kinds)

    def test_job_error_is_not_success(self):
        kinds = self.run_result({'id': 'job', 'status': 'succeeded', 'result': TODAY, 'error': {'code': 'failed'}})
        self.assertNotIn('result', kinds)


class ChartCoordinateTests(unittest.TestCase):
    def test_negative_stacks_are_separate(self):
        result = prepare_chart({'series': [
            {'type': 'bar', 'stack': 's', 'data': [10, -10]},
            {'type': 'bar', 'stack': 's', 'data': [5, -5]},
        ]})
        self.assertEqual([p['y'] for p in result['series'][1]['coordinates']], [15, -15])
        self.assertEqual(result['axes'][0]['min'], -15)
        self.assertEqual(result['axes'][0]['max'], 15)

    def test_value_axis_preserves_spacing_and_null(self):
        result = prepare_chart({'xAxis': {'type': 'value'}, 'series': [{'type': 'line', 'data': [[1, 3], [2, None], [10, 5]]}]})
        self.assertEqual([p['x'] for p in result['series'][0]['coordinates']], [1, 2, 10])
        self.assertIsNone(result['series'][0]['coordinates'][1]['y'])

    def test_data_min_max_are_not_forced_to_zero(self):
        result = prepare_chart({'yAxis': {'min': 'dataMin', 'max': 'dataMax'}, 'series': [{'data': [20, 30]}]})
        self.assertEqual((result['axes'][0]['min'], result['axes'][0]['max']), (20, 30))


class PackagingTests(unittest.TestCase):
    def test_missing_backend_never_creates_client_only_archive(self):
        import tempfile
        spec = importlib.util.spec_from_file_location('linux_package', ROOT / 'src/native/linux/package.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.package(Path(tmp) / 'missing', Path(tmp) / 'out')
            self.assertFalse((Path(tmp) / 'out').exists())

    def test_non_linux_backend_is_rejected(self):
        import tempfile
        spec = importlib.util.spec_from_file_location('linux_package', ROOT / 'src/native/linux/package.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / 'VantageBackend'
            backend.write_bytes(b'MZ not a Linux runtime')
            backend.chmod(0o755)
            with self.assertRaises(ValueError):
                module.package(backend, Path(tmp) / 'out')

class MediaTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_fixture()
        cls.client = Client(f'http://127.0.0.1:{cls.server.server_address[1]}')
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
    def test_camera_frames_and_registry_cleanup(self):
        for _ in range(3):
            frames = list(self.client.frames(threading.Event()))
            self.assertEqual(len(frames), 3)
            self.assertTrue(all(frame.startswith(b'\xff\xd8') and frame.endswith(b'\xff\xd9') for frame in frames))
            self.assertFalse(self.client.active.get('/api/v1/camera/stream'))
    def test_static_images_and_valid_excel_export(self):
        import io
        import zipfile
        latest = self.client.request('/api/v1/media/latest')
        self.assertTrue(self.client.download(latest['photo']).startswith(b'\x89PNG'))
        with zipfile.ZipFile(io.BytesIO(self.client.download('/api/v1/face/export'))) as archive:
            self.assertIn('xl/workbook.xml', archive.namelist())
    def test_numeric_time_axis_milliseconds(self):
        chart = prepare_chart({'xAxis': {'type': 'time'}, 'series': [{'type': 'line', 'data': [[1000000, 2], [1100000, 3]]}]})
        self.assertEqual([p['x'] for p in chart['series'][0]['coordinates']], [1000, 1100])

class HostLifecycleTests(unittest.TestCase):
    def test_closed_host_does_not_launch(self):
        from vantage_linux.lifecycle import BackendHost
        from unittest.mock import patch
        host = BackendHost(Client('http://127.0.0.1:9'), ['/unused/backend'])
        host.close()
        with patch('vantage_linux.lifecycle.subprocess.Popen') as popen:
            with self.assertRaises(ClientError):
                host.connect(timeout=.01)
            popen.assert_not_called()

    def test_start_failure_cleans_owned_state_and_can_retry(self):
        import tempfile
        from vantage_linux.lifecycle import BackendHost
        from unittest.mock import patch
        class Offline:
            base_url = 'http://127.0.0.1:9'
            def request(self, path):
                raise ClientError('Cannot reach the local backend')
        with tempfile.TemporaryDirectory() as tmp:
            host = BackendHost(Offline(), ['/unused/backend'], tmp)
            with patch('vantage_linux.lifecycle.subprocess.Popen', side_effect=OSError('Synthetic spawn failure')):
                for _ in range(2):
                    with self.assertRaises(OSError):
                        host.connect(timeout=.01)
                    self.assertIsNone(host.process)
                    self.assertIsNone(host.lock)
                    self.assertFalse(host.stopped.is_set())
            host.close()

class NativeMarkdownTests(unittest.TestCase):
    def test_structured_markdown_without_raw_heading_or_task_markers(self):
        from vantage_linux.markdown import markdown_blocks
        blocks = markdown_blocks('# Heading\n\n- [ ] Task\n- [x] Done\n> Quote\n```python\nprint("hello")\n```')
        self.assertEqual(blocks[0], ('h1', [('Heading', None)]))
        self.assertIn(('list', [('☐  ', None), ('Task', None)]), blocks)
        self.assertIn(('pre', [('print("hello")', None)]), blocks)
        self.assertNotIn('```', ''.join(text for _, runs in blocks for text, _ in runs))
    def test_table_keeps_cjk_columns_and_values(self):
        from vantage_linux.markdown import markdown_blocks
        blocks = markdown_blocks('| 项目 | 值 |\n| --- | --- |\n| 阅读 | 30 |')
        self.assertEqual(blocks[0][0], 'table-head')
        self.assertEqual(blocks[-1][0], 'table')
        self.assertIn('阅读', blocks[-1][1][0][0])
    def test_inline_tags_and_links_are_text_not_html(self):
        from vantage_linux.markdown import inline_runs
        runs = inline_runs('**Strong** and `code` [site](https://example.test)')
        self.assertIn(('Strong', 'bold'), runs)
        self.assertIn(('code', 'code'), runs)
        self.assertIn(('site (https://example.test)', 'link'), runs)
        self.assertEqual(inline_runs('<script>value</script>'), [('<script>value</script>', None)])

class RecorderCleanupTests(unittest.TestCase):
    def recorder(self, code=1):
        import tempfile
        from unittest.mock import Mock
        from vantage_linux.recorder import Recorder
        recorder = Recorder()
        handle = tempfile.NamedTemporaryFile(prefix='vantage-recorder-test-', suffix='.wav', delete=False)
        handle.close()
        recorder.path = handle.name
        recorder.process = Mock(returncode=code)
        return recorder
    def test_permission_failure_cleanup_never_blocks_quit(self):
        recorder = self.recorder(1)
        path = Path(recorder.path)
        recorder.discard()
        self.assertIsNone(recorder.process)
        self.assertIsNone(recorder.path)
        self.assertFalse(path.exists())
        recorder.discard()  # Navigation + quit can clean up twice.
    def test_explicit_stop_reports_permission_failure_and_cleans_file(self):
        recorder = self.recorder(1)
        path = Path(recorder.path)
        with self.assertRaisesRegex(RuntimeError, 'permission denied'):
            recorder.stop()
        self.assertFalse(path.exists())
        self.assertIsNone(recorder.process)
    def test_spawn_failure_cleans_created_recording_file(self):
        from unittest.mock import patch
        from vantage_linux.recorder import Recorder
        recorder = Recorder()
        recorder.tool = '/synthetic/pw-record'
        with patch('vantage_linux.recorder.subprocess.Popen', side_effect=PermissionError()):
            with self.assertRaisesRegex(RuntimeError, 'Could not start'):
                recorder.start()
        self.assertIsNone(recorder.path)
        self.assertIsNone(recorder.process)
