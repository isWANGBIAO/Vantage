"""Real Node probing must not create the job it is trying to rule out.

Only newly-created synthetic Node/Python processes are used. No installed app,
user settings, Codex process, or real desktop process is stopped or modified.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest


NODE_HOST = r'''
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const [helper, python, root, output, control] = process.argv.slice(1);
const { prepareIndependentLaunch } = require(helper);
let probe = null;
let detached = null;
const pythonProbe = 'import json,sys;sys.path.insert(0,sys.argv[1]);'
    + 'from src.core.windows_process_launch import inspect_process;'
    + 'print(json.dumps(inspect_process(int(sys.argv[2]))))';
try {
    const result = prepareIndependentLaunch({
        platform: 'win32', isPackaged: true, appExecutable: process.execPath,
        backendExecutable: python, pid: process.pid,
        argv: [process.execPath, '--vantage-independent-start'],
        spawnSyncProcess: (_executable, args, settings) => {
            if (args[0] !== '--diagnostics-isolation') throw new Error('unexpected-mode');
            const options = { ...settings };
            if (control === 'ordinary') delete options.detached;
            detached = options.detached === true;
            const response = spawnSync(python, ['-c', pythonProbe, root, args[1]], options);
            if (response.status === 0) probe = JSON.parse(response.stdout);
            return response;
        },
    });
    fs.writeFileSync(output, JSON.stringify({ result, probe, detached }));
} catch {
    fs.writeFileSync(output, JSON.stringify({ failed: true }));
}
// Keep this exact owned process alive long enough to retain a native handle.
setTimeout(() => {}, 30000);
'''


@pytest.fixture
def native_launcher():
    if sys.platform != 'win32':
        pytest.skip('requires Windows with an interactive Explorer desktop')
    from src.core import windows_process_launch
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetShellWindow.argtypes = ()
    user.GetShellWindow.restype = wintypes.HWND
    if not user.GetShellWindow():
        pytest.skip('requires an interactive Explorer desktop, absent in service CI')
    return windows_process_launch


@pytest.mark.parametrize('ordinary_control', [True, False], ids=['ordinary-control', 'product-probe'])
def test_real_node_probe_does_not_assign_its_host_to_a_libuv_job(
    tmp_path, native_launcher, ordinary_control,
):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for native child-process integration')
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'node-probe.json'
    helper = root / 'src/webapp/src/utils/desktopLaunch.cjs'
    launched = native_launcher.launch_from_desktop(
        [str(Path(node).resolve()), '-e', NODE_HOST, str(helper), sys.executable,
         str(root), str(output), 'ordinary' if ordinary_control else 'product'],
        cwd=str(root), environment=dict(os.environ), hide=True,
    )
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    # Retain the exact synthetic process, so PID reuse cannot redirect cleanup.
    handle = kernel.OpenProcess(0x101001, False, launched['pid'])
    assert handle, 'unable to retain the newly-created synthetic Node process'
    try:
        assert launched['identity']['inJob'] is False
        assert launched['identity']['hasPackageIdentity'] is False
        assert launched['identity']['parentIsShell'] is True
        deadline = time.monotonic() + 15
        value = None
        while time.monotonic() < deadline:
            try:
                value = json.loads(output.read_text(encoding='utf-8'))
                break
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(.025)
        assert value is not None, 'synthetic Node did not publish its probe result'
        assert not value.get('failed'), 'synthetic Node probe did not complete'
        assert value['probe']['pid'] == launched['pid']
        assert value['probe']['hasPackageIdentity'] is False
        assert value['probe']['parentIsShell'] is True
        if ordinary_control:
            # This reproduces the old bug: the probe's own uv_spawn creates a
            # libuv job and assigns the parent Node host to it before inspecting.
            assert value['detached'] is False
            assert value['probe']['inJob'] is True
            assert value['result']['action'] == 'failed'
        else:
            assert value['detached'] is True
            assert value['probe']['inJob'] is False
            assert value['result']['action'] == 'continue'
            assert value['result']['identity']['pid'] == launched['pid']
            assert value['result']['identity']['inJob'] is False
    finally:
        kernel.TerminateProcess(handle, 0)
        kernel.WaitForSingleObject(handle, 5000)
        kernel.CloseHandle(handle)
