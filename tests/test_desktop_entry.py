import importlib
import json
from pathlib import Path

import pytest


def entry():
    try:
        return importlib.import_module('src.core.desktop_entry')
    except ModuleNotFoundError:
        pytest.fail('independent desktop entry is not implemented')


def test_isolation_probe_returns_verified_metadata_not_process_paths(capsys):
    module = entry()
    identity = dict(pid=123, parentPid=10, inJob=False, hasPackageIdentity=False,
                    parentIsShell=True, isIndependent=True, createdAt='2026-10-31T10:00:00.000Z')
    code = module.main(['--diagnostics-isolation', '123'], inspect=lambda _pid: {
        **identity, 'privatePath': 'PRIVATE_SECRET'})
    assert code == 0
    value = json.loads(capsys.readouterr().out)
    assert value == identity


def test_desktop_launch_only_allows_own_installed_gui_and_fixed_arguments(tmp_path, capsys):
    module = entry()
    backend = tmp_path / 'Vantage' / 'resources' / 'backend-runtime' / 'VantageBackend' / 'VantageBackend.exe'
    gui = tmp_path / 'Vantage' / 'Vantage.exe'
    gui.parent.mkdir(); gui.write_bytes(b'synthetic')
    calls = []
    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return dict(pid=456, isolation='desktop-independent', identity={
            'pid': 456, 'parentPid': 10, 'inJob': False, 'hasPackageIdentity': False,
            'parentIsShell': True, 'isIndependent': True, 'createdAt': '2026-10-31T10:00:00.000Z'})
    code = module.main(['--launch-desktop-app', str(gui)], executable=backend,
                       frozen=True, launch=launch, env={'SystemRoot': 'Windows', 'API_KEY': 'PRIVATE_SECRET'})
    assert code == 0
    assert calls[0][0] == [str(gui), '--vantage-independent-start']
    assert calls[0][1]['hide'] is False
    assert calls[0][1]['environment']['VANTAGE_APP_MODE'] == 'packaged'
    assert 'API_KEY' not in calls[0][1]['environment']
    assert json.loads(capsys.readouterr().out)['isolation'] == 'desktop-independent'
    assert module.main(['--launch-desktop-app', str(tmp_path / 'other.exe')], executable=backend,
                       frozen=True, launch=launch) == 2
    assert len(calls) == 1
    assert module.main(['--launch-desktop-app', str(gui), '--untrusted-argument'],
                       executable=backend, frozen=True, launch=launch) == 2
    assert len(calls) == 1


def test_launch_failure_is_bounded_and_never_falls_back(tmp_path, capsys):
    module = entry()
    backend = tmp_path / 'Vantage' / 'resources' / 'backend-runtime' / 'VantageBackend' / 'VantageBackend.exe'
    gui = tmp_path / 'Vantage' / 'Vantage.exe'; gui.parent.mkdir(); gui.touch()
    def fail(*_args, **_kwargs):
        raise PermissionError('PRIVATE_SECRET')
    assert module.main(['--launch-desktop-app', str(gui)], executable=backend,
                       frozen=True, launch=fail) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_SECRET' not in output
    assert json.loads(output)['status'] == 'failed'


def test_packaged_modes_are_dispatched_before_config_import():
    source = Path('src/scripts/run_server_background.py').read_text(encoding='utf-8')
    assert source.index('"--launch-desktop-app"') < source.index('from src.core.config import Config')
    assert source.index('"--diagnostics-isolation"') < source.index('from src.core.config import Config')


def test_windows_product_environment_is_case_insensitive_and_keeps_only_known_fields():
    assert entry().desktop_environment({'vantage_data_dir': 'custom-profile',
        'Vantage_Backend_Port': '8001', 'VANTAGE_API_KEY': 'PRIVATE_SECRET'}) == {
        'VANTAGE_DATA_DIR': 'custom-profile', 'VANTAGE_BACKEND_PORT': '8001',
        'VANTAGE_APP_MODE': 'packaged'}
