import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import server
from src.core import user_config
from src.services.automation_catalog import get_operation


def _use_runtime_dirs(monkeypatch, root: Path):
    paths = {
        "data": root / "data",
        "config": root / "config",
        "history": root / "data" / "history",
        "logs": root / "data" / "logs",
        "plots": root / "data" / "plots",
        "cache": root / "data" / "cache",
        "runtime": root / "data" / "runtime",
        "migration": root / "data" / "migration",
    }
    for name, path in paths.items():
        method_name = {
            "data": "get_data_dir",
            "config": "get_config_dir",
            "history": "get_history_dir",
            "logs": "get_logs_dir",
            "plots": "get_plot_dir",
            "cache": "get_cache_dir",
            "runtime": "get_runtime_dir",
            "migration": "get_migration_dir",
        }[name]
        monkeypatch.setattr(server.Config, method_name, staticmethod(lambda path=path: path))
    monkeypatch.setattr(server.Config, "get_project_root", staticmethod(lambda: root / "project"))
    return paths


def _run_concurrent_updates_with_stale_read_gate(monkeypatch, loader_name, first_update, second_update):
    original_loader = getattr(server, loader_name)
    first_read = threading.Event()
    second_read = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    first_done = threading.Event()
    second_done = threading.Event()
    thread_local = threading.local()
    errors = []

    def gated_loader():
        state = original_loader()
        thread_name = threading.current_thread().name
        if thread_name in {"settings-update-first", "settings-update-second"} and not getattr(
            thread_local, "paused", False
        ):
            thread_local.paused = True
            if thread_name == "settings-update-first":
                first_read.set()
                if not release_first.wait(5):
                    raise TimeoutError("first settings update was not released")
            else:
                second_read.set()
                if not release_second.wait(5):
                    raise TimeoutError("second settings update was not released")
        return state

    monkeypatch.setattr(server, loader_name, gated_loader)

    def run_update(update, done):
        try:
            update()
        except Exception as error:  # surfaced in the main test thread below
            errors.append(error)
        finally:
            done.set()

    first_thread = threading.Thread(
        target=run_update,
        args=(first_update, first_done),
        name="settings-update-first",
    )
    second_thread = threading.Thread(
        target=run_update,
        args=(second_update, second_done),
        name="settings-update-second",
    )
    first_thread.start()
    assert first_read.wait(5), "first update did not reach its read phase"
    second_thread.start()

    if second_read.wait(1):
        # Without serialization both requests have captured the same old state.
        release_second.set()
        assert second_done.wait(5), "second update did not finish"
        release_first.set()
    else:
        # With serialization the second request cannot read until the first commits.
        release_first.set()
        assert first_done.wait(5), "first update did not finish"
        assert second_read.wait(5), "second update did not reach its serialized read phase"
        release_second.set()

    assert first_done.wait(5), "first update did not finish"
    assert second_done.wait(5), "second update did not finish"
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors, f"concurrent settings update failed: {errors!r}"


def test_settings_and_onboarding_catalog_operations_use_shared_backend_routes():
    expected = {
        "settings.state.read": ("GET", "/api/automation/settings"),
        "settings.update": ("PUT", "/api/automation/settings"),
        "settings.display_language.read": ("GET", "/api/automation/settings/display-language"),
        "settings.display_language.update": ("PUT", "/api/automation/settings/display-language"),
        "onboarding.state.read": ("GET", "/api/automation/onboarding"),
        "onboarding.complete": ("POST", "/api/automation/onboarding/complete"),
    }

    for name, (method, path) in expected.items():
        operation = get_operation(name)
        assert operation.availability == "available"
        assert operation.dispatchable is True
        assert (operation.method, operation.path) == (method, path)


def test_settings_read_update_round_trip_uses_python_json_and_masks_secrets(tmp_path, monkeypatch):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings(
        {
            "display_language": "en-US",
            "voice_provider_mode": "custom",
            "voice_api_key": "voice-secret",
        }
    )
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "providers": {
                "local": {
                    "route": "local",
                    "api_key": "provider-secret",
                    "base_url": "http://127.0.0.1:8317/v1",
                    "model": "model-a",
                }
            },
        }
    )

    state = server.get_automation_settings()
    assert state["settings"]["display_language"] == "en-US"
    assert state["settings"]["voice_api_key"] == "********"
    assert state["settings"]["voice_has_api_key"] is True
    assert state["provider"]["providers"]["local"]["api_key"] == "********"
    assert "voice-secret" not in json.dumps(state)
    assert "provider-secret" not in json.dumps(state)

    updated = server.update_automation_settings(
        {
            "display_language": "zh-CN",
            "action_plan_check_interval_minutes": 0,
            "voice_api_key": "********",
            "provider_config": state["provider"],
        }
    )

    assert updated["settings"]["display_language"] == "zh-CN"
    assert updated["settings"]["action_plan_check_interval_minutes"] == 0
    assert user_config.load_settings()["voice_api_key"] == "voice-secret"
    assert user_config.load_provider_config()["providers"]["local"]["api_key"] == "provider-secret"
    assert paths["config"].joinpath("settings.json").exists()
    assert paths["config"].joinpath("providers.json").exists()


def test_concurrent_display_language_and_settings_updates_preserve_both_fields(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"display_language": "en-US", "action_plan_auto_generate": False})

    _run_concurrent_updates_with_stale_read_gate(
        monkeypatch,
        "load_settings",
        lambda: server.update_automation_display_language({"display_language": "zh-CN"}),
        lambda: server.update_automation_settings({"action_plan_auto_generate": True}),
    )

    settings = user_config.load_settings()
    assert settings["display_language"] == "zh-CN"
    assert settings["action_plan_auto_generate"] is True


def test_concurrent_provider_selection_and_entry_update_preserve_both_changes(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_provider_config(
        {
            "selected_provider": "primary",
            "providers": {
                "primary": {"route": "primary", "model": "primary-old"},
                "secondary": {"route": "secondary", "model": "secondary-old"},
            },
        }
    )

    _run_concurrent_updates_with_stale_read_gate(
        monkeypatch,
        "load_provider_config",
        lambda: server.update_automation_settings(
            {"provider_config": {"selected_provider": "secondary"}}
        ),
        lambda: server.update_automation_settings(
            {
                "provider_config": {
                    "providers": {
                        "primary": {"model": "primary-new"},
                        "secondary": {"model": "secondary-old"},
                    }
                }
            }
        ),
    )

    provider = user_config.load_provider_config()
    assert provider["selected_provider"] == "secondary"
    assert provider["providers"]["primary"]["model"] == "primary-new"


def test_settings_update_preserves_model_profiles_and_provider_capabilities_when_form_omits_them(
    tmp_path, monkeypatch
):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "sampling_defaults": {"temperature": 0.83, "top_p": 0.91, "top_k": 13},
            "model_profiles": {
                "custom-model-*": {
                    "parameters": {"temperature": 0.42},
                    "omit_parameters": ["frequency_penalty"],
                }
            },
            "providers": {
                "local": {
                    "route": "local",
                    "api_key": "provider-secret",
                    "base_url": "http://127.0.0.1:8317/v1",
                    "model": "custom-model-v1",
                    "context_window_tokens": 131072,
                    "max_output_tokens": 32768,
                }
            },
        }
    )

    canonical_state = server.get_automation_settings()
    canonical_provider = canonical_state["provider"]["providers"]["local"]
    assert canonical_provider["context_window_tokens"] == 131072
    assert canonical_provider["max_output_tokens"] == 32768
    form_provider_config = {
        "version": canonical_state["provider"]["version"],
        "selected_provider": canonical_state["provider"]["selected_provider"],
        # Mirror the UI/IPC projection: editable provider values, but no
        # model-level defaults/profiles or non-editable capability fields.
        "providers": {
            "local": {
                key: canonical_state["provider"]["providers"]["local"][key]
                for key in (
                    "route",
                    "name",
                    "type",
                    "enabled",
                    "api_key",
                    "base_url",
                    "model",
                    "models",
                    "last_refreshed_at",
                )
            }
        },
    }
    server.update_automation_settings({"provider_config": form_provider_config})

    readback_provider = server.get_automation_settings()["provider"]["providers"]["local"]
    assert readback_provider["context_window_tokens"] == 131072
    assert readback_provider["max_output_tokens"] == 32768
    persisted = user_config.load_provider_config()
    assert persisted["sampling_defaults"]["temperature"] == 0.83
    assert persisted["sampling_defaults"]["top_p"] == 0.91
    assert persisted["sampling_defaults"]["top_k"] == 13
    assert persisted["model_profiles"]["custom-model-*"]["parameters"]["temperature"] == 0.42
    assert persisted["model_profiles"]["custom-model-*"]["omit_parameters"] == ["frequency_penalty"]
    assert persisted["providers"]["local"]["context_window_tokens"] == 131072
    assert persisted["providers"]["local"]["max_output_tokens"] == 32768


def test_settings_update_keeps_explicit_provider_deletion_intent(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "providers": {
                "local": {"route": "local", "base_url": "http://127.0.0.1/v1", "model": "model-a"},
                "retired": {"route": "retired", "base_url": "http://127.0.0.1/v2", "model": "model-b"},
            },
        }
    )

    server.update_automation_settings(
        {
            "provider_config": {
                "selected_provider": "local",
                "providers": {
                    "local": {"route": "local", "base_url": "http://127.0.0.1/v1", "model": "model-a"}
                },
            }
        }
    )

    assert set(user_config.load_provider_config()["providers"]) == {"local"}


def test_settings_update_rejects_action_plan_interval_above_catalog_limit(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"action_plan_check_interval_minutes": 30})

    server.update_automation_settings({
        "action_plan_check_interval_minutes": user_config.MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES,
    })
    assert user_config.load_settings()["action_plan_check_interval_minutes"] == 35_791

    with pytest.raises(HTTPException, match="action_plan_check_interval_minutes"):
        server.update_automation_settings({"action_plan_check_interval_minutes": 35_792})

    assert user_config.load_settings()["action_plan_check_interval_minutes"] == 35_791


def test_settings_partial_provider_config_without_providers_preserves_provider_set_and_selection(
    tmp_path, monkeypatch
):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_provider_config(
        {
            "selected_provider": "secondary",
            "sampling_defaults": {"temperature": 0.83},
            "providers": {
                "primary": {"route": "primary", "base_url": "http://127.0.0.1/v1", "model": "model-a"},
                "secondary": {"route": "secondary", "base_url": "http://127.0.0.1/v2", "model": "model-b"},
            },
        }
    )

    server.update_automation_settings(
        {
            "provider_config": {
                "sampling_defaults": {"temperature": 0.71},
                "model_profiles": {"partial-only-*": {"parameters": {"top_p": 0.62}}},
            }
        }
    )

    persisted = user_config.load_provider_config()
    assert persisted["selected_provider"] == "secondary"
    assert set(persisted["providers"]) == {"primary", "secondary"}
    assert persisted["sampling_defaults"]["temperature"] == 0.71
    assert persisted["model_profiles"]["partial-only-*"]["parameters"]["top_p"] == 0.62


@pytest.mark.parametrize(
    "submitted_providers",
    [
        pytest.param(None, id="null-provider-map"),
        pytest.param({"broken": None}, id="non-object-provider-entry"),
    ],
)
def test_settings_update_rejects_invalid_provider_config_before_writing_any_json(
    tmp_path, monkeypatch, submitted_providers
):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"display_language": "en-US"})
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "providers": {
                "local": {
                    "route": "local",
                    "base_url": "http://127.0.0.1:8317/v1",
                    "model": "model-a",
                }
            },
        }
    )
    settings_file = paths["config"] / "settings.json"
    providers_file = paths["config"] / "providers.json"
    settings_before = settings_file.read_bytes()
    providers_before = providers_file.read_bytes()

    with pytest.raises(HTTPException) as error:
        server.update_automation_settings(
            {
                "display_language": "zh-CN",
                "provider_config": {"providers": submitted_providers},
            }
        )

    assert error.value.status_code == 422
    assert settings_file.read_bytes() == settings_before
    assert providers_file.read_bytes() == providers_before


def test_settings_update_rolls_back_both_json_files_when_provider_write_fails(tmp_path, monkeypatch):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"display_language": "en-US"})
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "providers": {
                "local": {
                    "route": "local",
                    "base_url": "http://127.0.0.1:8317/v1",
                    "model": "model-a",
                }
            },
        }
    )
    settings_file = paths["config"] / "settings.json"
    providers_file = paths["config"] / "providers.json"
    settings_before = settings_file.read_bytes()
    providers_before = providers_file.read_bytes()
    save_provider_config = server.save_provider_config

    def save_provider_then_fail(payload):
        save_provider_config(payload)
        raise OSError("simulated failure after provider config write")

    monkeypatch.setattr(server, "save_provider_config", save_provider_then_fail)
    with pytest.raises(OSError, match="simulated failure"):
        server.update_automation_settings(
            {
                "display_language": "zh-CN",
                "provider_config": {
                    "providers": {
                        "local": {
                            "route": "local",
                            "base_url": "http://127.0.0.1:8317/v1",
                            "model": "model-b",
                        }
                    }
                },
            }
        )

    assert settings_file.read_bytes() == settings_before
    assert providers_file.read_bytes() == providers_before


def test_onboarding_state_and_completion_import_only_into_configured_history(tmp_path, monkeypatch):
    paths = _use_runtime_dirs(monkeypatch, tmp_path)
    legacy_root = tmp_path / "selected-legacy-root"
    source_history = legacy_root / "history"
    source_history.mkdir(parents=True)
    (source_history / "action_plan.json").write_text("legacy", encoding="utf-8")
    (paths["history"] / "keep.json").parent.mkdir(parents=True)
    (paths["history"] / "keep.json").write_text("newer", encoding="utf-8")

    before = server.get_automation_onboarding_state()
    assert before["completed"] is False
    assert before["migrationCompleted"] is False

    result = server.complete_automation_onboarding(
        {
            "display_language": "zh-CN",
            "launch_at_login": True,
            "selected_provider": "custom",
            "base_url": "http://127.0.0.1:8317/v1",
            "api_key": "onboarding-secret",
            "model": "model-b",
            "skip_chat_setup": False,
            "import_legacy_data": True,
            "legacy_root": str(legacy_root),
        }
    )

    assert result["completed"] is True
    assert result["providerConfigured"] is True
    assert result["migration"]["imported"] is True
    assert (paths["history"] / "action_plan.json").read_text(encoding="utf-8") == "legacy"
    assert (paths["history"] / "keep.json").read_text(encoding="utf-8") == "newer"
    assert user_config.load_settings()["onboarding_completed"] is True
    assert user_config.load_provider_config()["providers"]["custom"]["api_key"] == "onboarding-secret"
    assert user_config.load_migration_state()["source_path"] == str(legacy_root.resolve())
    assert server.get_automation_onboarding_state()["migrationCompleted"] is True
    assert "onboarding-secret" not in json.dumps(server.get_automation_settings())


def test_onboarding_rejects_missing_history_before_changing_configuration(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    invalid_root = tmp_path / "not-a-legacy-root"
    invalid_root.mkdir()

    with pytest.raises(HTTPException, match="history"):
        server.complete_automation_onboarding(
            {
                "selected_provider": "custom",
                "api_key": "secret",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "model-c",
                "skip_chat_setup": False,
                "import_legacy_data": True,
                "legacy_root": str(invalid_root),
            }
        )

    assert user_config.load_settings()["onboarding_completed"] is False
    assert user_config.load_provider_config()["providers"] == {}


def test_onboarding_requires_explicit_chat_setup_choice_before_mutating_settings(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"theme": "light", "display_language": "en-US"})
    user_config.save_provider_config({
        "selected_provider": "local",
        "providers": {
            "local": {
                "route": "local",
                "api_key": "preserved-secret",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "existing-model",
            }
        },
    })
    settings_before = user_config.load_settings()
    provider_before = user_config.load_provider_config()

    with pytest.raises(HTTPException, match="skip_chat_setup"):
        server.complete_automation_onboarding({})

    assert user_config.load_settings() == settings_before
    assert user_config.load_provider_config() == provider_before


def test_onboarding_requires_selected_provider_when_chat_setup_is_not_skipped(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)

    with pytest.raises(HTTPException, match="selected_provider"):
        server.complete_automation_onboarding({"skip_chat_setup": False})

    assert user_config.load_settings()["onboarding_completed"] is False
    assert user_config.load_provider_config()["providers"] == {}


def test_skipping_chat_setup_preserves_existing_provider_configuration(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"launch_at_login": True})
    provider_before = user_config.save_provider_config({
        "selected_provider": "custom",
        "sampling_defaults": {"temperature": 0.83, "top_p": 0.91},
        "model_profiles": {"custom-*": {"parameters": {"top_p": 0.75}}},
        "providers": {
            "custom": {
                "route": "custom",
                "api_key": "preserved-secret",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "existing-model",
            },
            "secondary": {
                "route": "secondary",
                "base_url": "https://example.invalid/v1",
                "model": "secondary-model",
            },
        },
    })
    provider_file = user_config.get_providers_file()
    provider_bytes_before = provider_file.read_bytes()

    result = server.complete_automation_onboarding({"skip_chat_setup": True})

    assert result["providerConfigured"] is True
    assert result["launchAtLogin"] is True
    assert user_config.load_settings()["launch_at_login"] is True
    assert user_config.load_provider_config() == provider_before
    assert provider_file.read_bytes() == provider_bytes_before


@pytest.mark.parametrize("launch_at_login", [None, "true", 1])
def test_onboarding_rejects_non_boolean_launch_at_login_before_mutating_settings(
    tmp_path, monkeypatch, launch_at_login
):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"launch_at_login": True})
    settings_before = user_config.load_settings()

    with pytest.raises(HTTPException, match="launch_at_login"):
        server.complete_automation_onboarding({
            "skip_chat_setup": True,
            "launch_at_login": launch_at_login,
        })

    assert user_config.load_settings() == settings_before


@pytest.mark.parametrize("submitted_api_key", ["", "********"])
def test_onboarding_provider_update_merges_existing_routes_and_preserves_blank_secret(
    tmp_path, monkeypatch, submitted_api_key
):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_provider_config({
        "selected_provider": "custom",
        "sampling_defaults": {"temperature": 0.83},
        "model_profiles": {"custom-*": {"parameters": {"top_p": 0.75}}},
        "providers": {
            "custom": {
                "route": "custom",
                "api_key": "preserved-secret",
                "base_url": "http://127.0.0.1:8317/v1",
                "model": "existing-model",
            },
            "secondary": {
                "route": "secondary",
                "base_url": "https://example.invalid/v1",
                "model": "secondary-model",
            },
        },
    })

    server.complete_automation_onboarding({
        "skip_chat_setup": False,
        "selected_provider": "custom",
        "api_key": submitted_api_key,
        "model": "updated-model",
    })

    provider = user_config.load_provider_config()
    assert provider["selected_provider"] == "custom"
    assert provider["sampling_defaults"]["temperature"] == 0.83
    assert provider["model_profiles"]["custom-*"]["parameters"]["top_p"] == 0.75
    assert provider["providers"]["custom"]["api_key"] == "preserved-secret"
    assert provider["providers"]["custom"]["base_url"] == "http://127.0.0.1:8317/v1"
    assert provider["providers"]["custom"]["model"] == "updated-model"
    assert provider["providers"]["secondary"]["model"] == "secondary-model"


def test_settings_and_onboarding_routes_reject_non_loopback_access():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/automation/settings"),
        client=SimpleNamespace(host="192.0.2.10"),
        headers={"host": "127.0.0.1:8000"},
    )

    async def accepted(_request):
        return "accepted"

    response = asyncio.run(server.enforce_loopback_backend_access(request, accepted))
    assert response.status_code == 403


def test_display_language_read_waits_for_shared_config_lock(monkeypatch):
    monkeypatch.setattr(server, "load_settings", lambda: {"display_language": "en-US"})
    started = threading.Event()
    completed = threading.Event()
    result = []

    def read_display_language():
        started.set()
        result.append(server.get_automation_display_language())
        completed.set()

    reader = threading.Thread(target=read_display_language)
    server._automation_config_lock.acquire()
    try:
        reader.start()
        started_in_time = started.wait(5)
        completed_while_locked = completed.wait(0.1) if started_in_time else False
    finally:
        server._automation_config_lock.release()

    reader.join(timeout=5)
    assert started_in_time, "display-language reader did not start"
    assert not completed_while_locked, "display-language read bypassed the shared configuration lock"
    assert not reader.is_alive()
    assert result == [{"display_language": "en-US"}]


def test_user_config_loader_waits_for_automation_config_lock(tmp_path, monkeypatch):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"display_language": "en-US"})
    started = threading.Event()
    completed = threading.Event()
    result = []

    def load_settings_in_worker():
        started.set()
        result.append(user_config.load_settings())
        completed.set()

    reader = threading.Thread(target=load_settings_in_worker)
    server._automation_config_lock.acquire()
    try:
        reader.start()
        started_in_time = started.wait(5)
        completed_while_locked = completed.wait(0.1) if started_in_time else False
        user_config.save_settings({"display_language": "zh-CN"})
    finally:
        server._automation_config_lock.release()

    reader.join(timeout=5)
    assert started_in_time, "user_config loader did not start"
    assert not completed_while_locked, "user_config loader bypassed the automation config lock"
    assert not reader.is_alive()
    assert result[0]["display_language"] == "zh-CN"


def test_special_provider_resolution_holds_one_lock_across_settings_and_provider_reads(
    tmp_path, monkeypatch
):
    _use_runtime_dirs(monkeypatch, tmp_path)
    user_config.save_settings({"voice_provider_mode": "inherit_ai", "voice_model": "voice-before"})
    user_config.save_provider_config(
        {
            "selected_provider": "local",
            "providers": {
                "local": {
                    "route": "local",
                    "api_key": "key-before",
                    "base_url": "https://before.example/v1",
                    "model": "provider-model",
                }
            },
        }
    )
    settings_loaded = threading.Event()
    continue_reader = threading.Event()
    writer_started = threading.Event()
    writer_completed = threading.Event()
    resolved = []
    errors = []
    original_load_settings = server.load_settings

    def pause_after_settings_read():
        settings = original_load_settings()
        if threading.current_thread().name == "special-provider-reader":
            settings_loaded.set()
            if not continue_reader.wait(5):
                raise TimeoutError("special-provider reader was not released")
        return settings

    monkeypatch.setattr(server, "load_settings", pause_after_settings_read)

    def read_special_provider():
        try:
            resolved.append(server._resolve_special_provider_config(kind="voice"))
        except Exception as error:
            errors.append(error)

    def update_provider():
        writer_started.set()
        try:
            user_config.save_provider_config(
                {
                    "selected_provider": "local",
                    "providers": {
                        "local": {
                            "route": "local",
                            "api_key": "key-after",
                            "base_url": "https://after.example/v1",
                            "model": "provider-model",
                        }
                    },
                }
            )
        except Exception as error:
            errors.append(error)
        finally:
            writer_completed.set()

    reader = threading.Thread(target=read_special_provider, name="special-provider-reader")
    writer = threading.Thread(target=update_provider, name="provider-config-writer")
    reader.start()
    assert settings_loaded.wait(5), "special-provider reader did not load settings"
    writer.start()
    assert writer_started.wait(5), "provider writer did not start"
    writer_completed_before_reader = writer_completed.wait(0.1)
    continue_reader.set()
    reader.join(timeout=5)
    writer.join(timeout=5)

    assert not reader.is_alive()
    assert not writer.is_alive()
    assert not errors, f"settings/provider read or write failed: {errors!r}"
    assert not writer_completed_before_reader, "provider write interleaved with the special-provider snapshot"
    assert resolved[0]["model"] == "voice-before"
    assert resolved[0]["api_key"] == "key-before"
    assert resolved[0]["base_url"] == "https://before.example/v1"


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("127.0.0.1:8000", "127.0.0.1"),
        ("localhost:8000", "localhost"),
        ("[::1]", "::1"),
        ("[::1]:8000", "::1"),
        ("::1", "::1"),
        ("localhost", "localhost"),
        ("testclient", "testclient"),
        ("testserver", "testserver"),
    ],
)
def test_loopback_host_parser_normalizes_local_host_forms(value, normalized):
    assert server._normalize_host_value(value) == normalized
    assert server._is_loopback_host(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "  ",
        "not a host",
        "localhost:invalid-port",
        "[::1]:invalid-port",
        "192.0.2.10",
        "2001:db8::1",
        "::1:8000",
        "::ffff:192.0.2.10",
    ],
)
def test_loopback_host_parser_fails_closed_for_empty_invalid_and_remote_hosts(value):
    assert server._is_loopback_host(value) is False


def test_loopback_host_parser_accepts_ipv4_mapped_loopback_address():
    assert server._is_loopback_host("::ffff:127.0.0.1") is True


def test_loopback_guard_does_not_change_existing_status_route_access():
    request = SimpleNamespace(
        url=SimpleNamespace(path="/api/status"),
        client=SimpleNamespace(host="192.0.2.10"),
        headers={"host": "192.0.2.20:8000"},
    )

    async def accepted(_request):
        return "accepted"

    response = asyncio.run(server.enforce_loopback_backend_access(request, accepted))
    assert response == "accepted"
