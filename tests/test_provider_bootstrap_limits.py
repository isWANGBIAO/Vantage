"""Cross-language persistence contract: HTTP save, packaged bootstrap, budget read."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend import settings
from src.core import user_config
from src.core.config import Config
from src.services.llm_client import LLMClient


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_http_provider_limits_survive_packaged_startup_and_keep_budget(tmp_path, monkeypatch, platform):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Cross-language packaged bootstrap requires Node.js")
    methods = {
        "get_data_dir": "data", "get_config_dir": "config", "get_history_dir": "history",
        "get_logs_dir": "logs", "get_plot_dir": "plots", "get_cache_dir": "cache",
        "get_runtime_dir": "runtime", "get_migration_dir": "migration", "get_project_root": "project",
    }
    for method, directory in methods.items():
        monkeypatch.setattr(Config, method, staticmethod(lambda directory=directory: tmp_path / directory))
    app = FastAPI()
    app.include_router(settings.router)
    http = TestClient(app, base_url="http://127.0.0.1")
    saved = http.put("/api/v1/settings", json={"provider_config": {
        "selected_provider": "primary", "providers": {
            "primary": {
                "api_key": "synthetic-primary", "base_url": "https://example.invalid/v1",
                "model": "synthetic-primary", "context_window_tokens": 16384, "max_output_tokens": 2048,
            },
            "backup": {
                "api_key": "synthetic-backup", "base_url": "https://backup.invalid/v1",
                "model": "synthetic-backup", "context_window_tokens": 32768, "max_output_tokens": 4096,
            },
        },
    }})
    assert saved.status_code == 200, saved.text

    def budget():
        client = object.__new__(LLMClient)
        client.providers = user_config.get_provider_chain_config()
        return client.get_prompt_budget()

    before = budget()
    assert before["input_budget_tokens"] == 12288
    script = r"""
const path = require('node:path');
const { ensureBundledBackendReady } = require('./src/webapp/src/utils/backendRuntime.cjs');
const root = process.argv[1];
const runtimePaths = Object.fromEntries(
  ['data','config','history','log','plot','cache','runtime','migration'].map(k => [k+'Dir',path.join(root,k)]));
let statusCalls = 0;
ensureBundledBackendReady({
  isDev: false, runtimePaths, env: {}, platform: process.argv[2],
  executablePath: path.join(root,'synthetic-backend'), fileExists: () => true,
  waitForStatusFn: async () => { if (++statusCalls === 1) throw Error('offline'); return {ready:true}; },
  spawnProcess: () => ({pid:0, exitCode:null, unref() {}}),
}).then(result => { if (!result.started) throw Error('bootstrap did not run'); });
"""
    subprocess.run(
        [node, "-e", script, str(tmp_path), platform],
        cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
    )
    readback = http.get("/api/v1/settings")
    assert readback.status_code == 200, readback.text
    actual = readback.json()["provider"]["providers"]
    for route, context, output in (("primary", 16384, 2048), ("backup", 32768, 4096)):
        assert actual[route]["context_window_tokens"] == context
        assert actual[route]["max_output_tokens"] == output
    assert budget() == before
    disk = json.loads((tmp_path / "config" / "providers.json").read_text(encoding="utf-8"))
    assert disk["providers"]["primary"]["context_window_tokens"] == 16384
