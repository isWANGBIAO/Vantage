"""Synthetic children only; never terminate an installed Vantage process."""
import importlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest


def observer():
    try:
        return importlib.import_module('src.core.exit_observer')
    except ModuleNotFoundError:
        pytest.fail('independent exit observer is not implemented')


def session(tmp_path, **changes):
    sid = str(uuid.uuid4())
    path = tmp_path / 'diagnostics' / 'sessions' / f'{sid}.active.json'
    path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    state = dict(schemaVersion=1, sessionId=sid, pid=os.getpid(), parentPid=os.getppid(),
                 startedAt=now, lastHeartbeatAt=now,
                 phase='running', backendPid=None)
    state.update(changes)
    path.write_text(json.dumps(state), encoding='utf-8')
    return path, state


def test_session_validation_drops_untrusted_fields(tmp_path):
    module = observer()
    path, state = session(tmp_path, secret='DO_NOT_PERSIST')
    result = module.read_session(path)
    assert result['sessionId'] == state['sessionId']
    assert 'secret' not in result
    assert result['pid'] == os.getpid()


def test_session_validation_rejects_bad_identity_and_links(tmp_path):
    module = observer()
    path, _ = session(tmp_path, sessionId='../outside')
    with pytest.raises(ValueError):
        module.read_session(path)
    path.unlink()
    outside = tmp_path / 'private.json'
    outside.write_text('{}')
    try:
        path.symlink_to(outside)
    except OSError:
        return
    with pytest.raises((ValueError, OSError)):
        module.read_session(path)


def test_events_are_atomic_bounded_and_allowlisted(tmp_path):
    module = observer()
    path, state = session(tmp_path)
    for index in range(8):
        module.record_exit(path, state, 'backend', pid=100 + index, exit_code=15,
                           observed_at='2026-10-29T01:00:06.000Z')
    directory = path.parent.parent / 'lifecycle'
    module.prune_history(directory, max_records=3, max_bytes=100000)
    records = list(directory.glob('exit-*.json'))
    assert len(records) == 3
    value = json.loads(records[-1].read_text())
    assert value['exitCode'] == 15
    assert value['sessionId'] == state['sessionId']
    assert value['reason'] == 'unexpected-exit'
    assert 'exitAt' in value and value['source'] == 'observer'
    assert not list(directory.glob('*.tmp'))


def test_code_zero_is_not_normal_unless_shutdown_was_requested(tmp_path):
    module = observer()
    path, state = session(tmp_path)
    first = module.record_exit(path, state, 'main', pid=100, exit_code=0)
    assert first['reason'] == 'unexpected-exit'
    state['phase'] = 'clean'
    second = module.record_exit(path, state, 'main', pid=101, exit_code=0)
    assert second['reason'] == 'normal-exit'
    assert module.record_exit(path, state, 'main', pid=102, exit_code=9)['reason'] == 'unexpected-exit'


def test_launcher_requests_breakaway_and_reports_fallback(tmp_path):
    module = observer()
    path, _ = session(tmp_path)
    calls = []
    class Child:
        pid = 123
    def spawn(command, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise PermissionError(5, 'private failure detail')
        return Child()
    status = module.launch_observer(path, command=['synthetic'], popen=spawn, platform='win32')
    assert calls[0]['creationflags'] & 0x01000000
    assert not calls[1]['creationflags'] & 0x01000000
    assert status['isolation'] == 'inherited-job'
    assert status['pid'] == 123
    assert 'private' not in json.dumps(status)


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows process handles')
def test_native_handle_survives_pid_exit_and_reports_exact_code(tmp_path):
    module = observer()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    handle = module.WindowsProcess(child.pid)
    try:
        assert handle.exit_code() is None
        assert handle.created_at
        child.terminate()
        child.wait(timeout=5)
        assert handle.exit_code() == child.returncode
    finally:
        handle.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows process identity')
def test_probe_rejects_pid_reuse_and_does_not_treat_access_denial_as_dead():
    module = observer()
    assert module.probe_process(os.getpid(), '2000-01-01T00:00:00.000Z')['alive'] is False
    assert module.probe_process(os.getpid(), module.utc_now())['alive'] is True
    def denied(_pid):
        raise PermissionError(5, 'PRIVATE_SECRET')
    assert module.probe_process(os.getpid(), module.utc_now(), process_factory=denied)['alive'] is None


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows shared-delete file semantics')
def test_observer_releases_read_handle_before_atomic_session_publication(tmp_path):
    module = observer()
    path, _ = session(tmp_path)
    assert module.read_session(path)['schemaVersion'] == 1
    replacement = path.with_name('replacement.tmp')
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    assert module.read_session(path)['schemaVersion'] == 1


def test_output_refuses_swapped_diagnostics_root(tmp_path):
    module = observer()
    path, state = session(tmp_path)
    root = path.parent.parent
    target = root / 'lifecycle'
    target.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'lifecycle').mkdir()
    root.rename(tmp_path / 'original-diagnostics')
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    with pytest.raises((ValueError, OSError)):
        module.atomic_json(target / 'exit-test.json', {'metadata': True})
    assert not (outside / 'lifecycle' / 'exit-test.json').exists()


def test_main_access_denied_is_failed_not_ready(tmp_path):
    module = observer()
    path, state = session(tmp_path)
    def denied(_pid):
        raise PermissionError(5, 'PRIVATE_SECRET')
    assert module.watch(path, process_factory=denied) == 2
    ack = json.loads((path.parent.parent / 'lifecycle' / f'watcher-{state["sessionId"]}.json').read_text())
    assert ack['status'] == 'failed'
    assert 'PRIVATE_SECRET' not in json.dumps(ack)


def test_backend_exit_identity_is_not_main_parent_or_start(tmp_path):
    module = observer()
    path, state = session(tmp_path, backendPid=999,
                          backendStartedAt='2026-10-29T02:00:00.000Z')
    value = module.record_exit(path, state, 'backend', pid=999, exit_code=9)
    assert value['parentPid'] == state['pid']
    assert value['startedAt'] == state['backendStartedAt']


def test_legal_atomic_snapshot_change_between_stat_and_open_is_not_failure(tmp_path, monkeypatch):
    module = observer()
    path, state = session(tmp_path)
    original = module.open_shared_read
    changed = False
    def swapped(filename):
        nonlocal changed
        if not changed:
            changed = True
            replacement = path.with_name('new.tmp')
            replacement.write_text(json.dumps(state))
            os.replace(replacement, path)
        return original(filename)
    monkeypatch.setattr(module, 'open_shared_read', swapped)
    assert module.read_session(path)['sessionId'] == state['sessionId']


def test_acknowledgement_retries_brief_windows_rename_contention(tmp_path, monkeypatch):
    module = observer()
    path, _ = session(tmp_path)
    directory = path.parent.parent / 'lifecycle'
    directory.mkdir()
    original = os.replace
    attempts = 0
    def locked_once(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(13, 'PRIVATE_SECRET')
        return original(source, target)
    monkeypatch.setattr(module.os, 'replace', locked_once)
    module.atomic_json(directory / 'watcher-test.json', {'status': 'ready'})
    assert attempts == 3
    assert json.loads((directory / 'watcher-test.json').read_text())['status'] == 'ready'


@pytest.mark.skipif(sys.platform != 'win32', reason='native Windows observer')
def test_actual_observer_records_forced_child_exit_without_application_writer(tmp_path):
    module = observer()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    path, state = session(tmp_path, pid=child.pid)
    watcher = subprocess.Popen([sys.executable, '-m', 'src.core.exit_observer', '--watch', str(path)],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    ready = path.parent.parent / 'lifecycle' / f'watcher-{state["sessionId"]}.json'
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert ready.exists(), 'observer must acknowledge process-handle readiness'
        child.terminate()
        child.wait(timeout=5)
        watcher.wait(timeout=8)
        assert watcher.returncode == 0
        records = [json.loads(p.read_text()) for p in ready.parent.glob('exit-*.json')]
        assert any(r['pid'] == child.pid and r['exitCode'] == child.returncode for r in records)
    finally:
        for proc in (child, watcher):
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_packaged_dispatch_precedes_config_and_heavy_imports(tmp_path):
    observer()
    script = str(Path('src/scripts/run_server_background.py').resolve())
    body = '''import sys, runpy, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'src.core.config':
            raise ImportError('heavy-import-was-reached')
sys.meta_path.insert(0, Block())
sys.argv = [sys.argv[1], '--diagnostics-watch', sys.argv[2]]
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as exc:
    print('observer-exit', exc.code)
except ImportError:
    print('heavy-import-was-reached')
'''
    result = subprocess.run([sys.executable, '-c', body, script, str(tmp_path / 'invalid')],
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == 0
    assert 'observer-exit 2' in result.stdout
    assert 'heavy-import-was-reached' not in result.stdout


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows breakaway launcher')
def test_real_detached_launcher_acknowledges_and_observes(tmp_path):
    module = observer()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    path, state = session(tmp_path, pid=child.pid)
    handle = None
    try:
        launch = module.launch_observer(path)
        handle = module.WindowsProcess(launch['pid'])
        ready = path.parent.parent / 'lifecycle' / f'watcher-{state["sessionId"]}.json'
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert json.loads(ready.read_text())['status'] == 'ready'
        child.terminate()
        child.wait(timeout=5)
        deadline = time.monotonic() + 8
        while handle.exit_code() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert handle.exit_code() == 0
    finally:
        if handle:
            handle.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows full-writer termination')
@pytest.mark.parametrize('kill_observer', [False, True])
def test_all_application_writers_killed_have_exit_evidence_or_restart_recovery(tmp_path, kill_observer):
    module = observer()
    backend = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    utility = str(Path('src/webapp/src/utils/crashDiagnostics.cjs').resolve())
    host_script = '''const {createCrashDiagnostics}=require(process.argv[1]);
const {EventEmitter}=require('node:events');
const d=createCrashDiagnostics({dataDir:process.env.VANTAGE_TEST_ROOT});
if(!d.startSession()) process.exit(2);
const backend=new EventEmitter(); backend.pid=Number(process.env.VANTAGE_TEST_BACKEND);
d.observeBackend(backend); d.startPeriodicCleanup();
console.log(JSON.stringify(d.getObserverSession())); setInterval(()=>{},1000);'''
    env = {**os.environ, 'VANTAGE_TEST_ROOT': str(tmp_path), 'VANTAGE_TEST_BACKEND': str(backend.pid)}
    host = subprocess.Popen(['node', '-e', host_script, utility], env=env, stdout=subprocess.PIPE,
                            text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    watcher = None
    try:
        identity = json.loads(host.stdout.readline())
        path = Path(identity['sessionPath'])
        before = module.read_session(path)
        watcher = subprocess.Popen([sys.executable, '-m', 'src.core.exit_observer', '--watch', str(path)],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        ready = path.parent.parent / 'lifecycle' / f'watcher-{identity["sessionId"]}.json'
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert json.loads(ready.read_text())['status'] == 'ready'
        if kill_observer:
            watcher.terminate()
            watcher.wait(timeout=5)
        host.terminate(); backend.terminate()
        host.wait(timeout=5); backend.wait(timeout=5)
        if not kill_observer:
            watcher.wait(timeout=8)
            assert watcher.returncode == 0
            records = [json.loads(p.read_text()) for p in ready.parent.glob('exit-*.json')]
            assert {r['processType'] for r in records if r['source'] == 'observer'} == {'main', 'backend'}
            assert all(r['exitAt'] and r['exitCode'] is not None for r in records if r['source'] == 'observer')
        recovery_script = '''const {createCrashDiagnostics}=require(process.argv[1]);
const d=createCrashDiagnostics({dataDir:process.env.VANTAGE_TEST_ROOT});
if(!d.startSession()) process.exit(2); console.log(JSON.stringify(d.getStatus())); d.markClean();'''
        recovered = subprocess.run(['node', '-e', recovery_script, utility], env=env,
                                   capture_output=True, text=True, timeout=8)
        assert recovered.returncode == 0, recovered.stderr
        assert json.loads(recovered.stdout)['previousInterrupted'] is True
        records = [json.loads(p.read_text()) for p in ready.parent.glob('exit-*.json')]
        old = next(r for r in records if r['source'] == 'recovery')
        assert old['sessionId'] == before['sessionId']
        assert old['lastHeartbeatAt'] == before['lastHeartbeatAt']
        assert old['observedAt'] is None
    finally:
        if host.stdout:
            host.stdout.close()
        for proc in (host, backend, watcher):
            if proc and proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows normal-exit observation')
def test_real_normal_shutdown_is_recorded_without_false_interruption(tmp_path):
    module = observer()
    utility = str(Path('src/webapp/src/utils/crashDiagnostics.cjs').resolve())
    script = '''const {createCrashDiagnostics}=require(process.argv[1]);
const d=createCrashDiagnostics({dataDir:process.env.VANTAGE_TEST_ROOT});
d.startSession(); console.log(JSON.stringify(d.getObserverSession()));
process.stdin.once('data',()=>{d.beginShutdown();d.markClean();process.exit(0)});'''
    env = {**os.environ, 'VANTAGE_TEST_ROOT': str(tmp_path)}
    host = subprocess.Popen(['node', '-e', script, utility], env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    watcher = None
    try:
        identity = json.loads(host.stdout.readline())
        path = Path(identity['sessionPath'])
        watcher = subprocess.Popen([sys.executable, '-m', 'src.core.exit_observer', '--watch', str(path)],
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        ready = path.parent.parent / 'lifecycle' / f'watcher-{identity["sessionId"]}.json'
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert json.loads(ready.read_text())['status'] == 'ready'
        host.stdin.write('quit\n'); host.stdin.flush()
        host.wait(timeout=5); watcher.wait(timeout=8)
        assert host.returncode == watcher.returncode == 0
        values = [json.loads(p.read_text()) for p in ready.parent.glob('exit-*.json')]
        assert any(v['source'] == 'observer' and v['reason'] == 'normal-exit' for v in values)
        assert not (path.parent.parent / 'electron-session.active.json').exists()
    finally:
        for stream in (host.stdin, host.stdout):
            if stream:
                stream.close()
        for proc in (host, watcher):
            if proc and proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)
