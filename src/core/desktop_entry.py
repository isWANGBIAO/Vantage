"""Allowlisted installed-app launch/probe modes, before service imports."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import sys

INDEPENDENT_START_ARG = '--vantage-independent-start'
IDENTITY_FIELDS = ('pid', 'parentPid', 'inJob', 'hasPackageIdentity', 'parentIsShell',
                   'isIndependent', 'createdAt')


def sanitize_identity(value, expected_pid=None):
    if not isinstance(value, dict):
        raise ValueError('invalid-process-identity')
    result = {key: value.get(key) for key in IDENTITY_FIELDS}
    for key in ('pid', 'parentPid'):
        if type(result[key]) is not int or not 0 < result[key] < 2**32:
            raise ValueError('invalid-process-identity')
    for key in ('inJob', 'hasPackageIdentity', 'parentIsShell', 'isIndependent'):
        if type(result[key]) is not bool:
            raise ValueError('unknown-process-identity')
    if expected_pid is not None and result['pid'] != expected_pid:
        raise ValueError('wrong-process-identity')
    if not isinstance(result['createdAt'], str) or len(result['createdAt']) > 40:
        raise ValueError('invalid-process-creation-time')
    stamp = datetime.fromisoformat(result['createdAt'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('invalid-process-creation-time')
    independent = not result['inJob'] and not result['hasPackageIdentity'] and result['parentIsShell']
    if result['isIndependent'] != independent:
        raise ValueError('inconsistent-process-identity')
    return result


def desktop_environment(env):
    standard = {'systemroot', 'windir', 'path', 'pathext', 'temp', 'tmp', 'localappdata',
                'appdata', 'userprofile', 'homedrive', 'homepath', 'username', 'userdomain'}
    product = {'VANTAGE_DATA_DIR', 'VANTAGE_CONFIG_DIR', 'VANTAGE_HISTORY_DIR', 'VANTAGE_LOG_DIR',
               'VANTAGE_PLOT_DIR', 'VANTAGE_CACHE_DIR', 'VANTAGE_RUNTIME_DIR', 'VANTAGE_MIGRATION_DIR',
               'VANTAGE_BACKEND_URL', 'VANTAGE_BACKEND_HOST', 'VANTAGE_BACKEND_PORT'}
    result = {key.upper() if key.upper() in product else key: value for key, value in env.items()
              if isinstance(value, str) and (key.lower() in standard or key.upper() in product)}
    result['VANTAGE_APP_MODE'] = 'packaged'
    return result


def _installed_gui(executable, requested):
    base = Path(os.path.abspath(executable)).parents[3]
    expected = base / 'Vantage.exe'
    if os.path.normcase(os.path.abspath(requested)) != os.path.normcase(str(expected)):
        raise ValueError('not-installed-gui')
    info = expected.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('unsafe-installed-gui')
    return expected


def main(argv=None, *, executable=None, frozen=None, launch=None, inspect=None, env=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 2 and args[0] == '--diagnostics-isolation':
            pid = int(args[1])
            if not 0 < pid < 2**32:
                raise ValueError('invalid-pid')
            if inspect is None:
                from src.core.windows_process_launch import inspect_process as inspect
            result = sanitize_identity(inspect(pid), pid)
        elif len(args) == 2 and args[0] == '--launch-desktop-app':
            if not (getattr(sys, 'frozen', False) if frozen is None else frozen):
                raise ValueError('installed-mode-required')
            gui = _installed_gui(executable or sys.executable, args[1])
            if launch is None:
                from src.core.windows_process_launch import launch_from_desktop as launch
            value = launch([str(gui), INDEPENDENT_START_ARG], hide=False, cwd=str(gui.parent),
                           environment=desktop_environment(os.environ if env is None else env))
            identity = sanitize_identity(value['identity'], value['pid'])
            if value.get('isolation') != 'desktop-independent' or not identity['isIndependent']:
                raise ValueError('unverified-desktop-launch')
            result = dict(pid=value['pid'], isolation='desktop-independent', identity=identity)
        else:
            raise ValueError('invalid-desktop-mode')
        print(json.dumps(result, separators=(',', ':')))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print(json.dumps(dict(status='failed', reason='desktop-launch-unavailable')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
