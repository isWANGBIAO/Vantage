import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.services.automation_catalog import (
    OPERATIONS,
    get_operation,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_OPERATION_NAMES = {
    "system.capabilities.read",
    "action_plan.source_revision.read",
    "action_plan.jobs.create",
    "action_plan.jobs.list",
    "action_plan.jobs.read",
    "action_plan.jobs.events",
    "action_plan.jobs.cancel",
    "action_plan.scheduler.read",
    "action_plan.today.read",
    "chat.context.read",
    "chat.context.reset",
    "chat.send",
    "face.analyze",
    "face.export",
    "face.live.read",
    "face.progress.read",
    "face.report.read",
    "finance.balance_sheet.read",
    "finance.recommendations.dismiss",
    "finance.recommendations.dismissed.clear",
    "finance.recommendations.dismissed.list",
    "finance.recommendations.dismissed.restore",
    "finance.recommendations.read",
    "finance.recommendations.regenerate",
    "logs.read",
    "media.transcribe",
    "models.discover",
    "models.list",
    "plots.read",
    "plots.refresh",
    "project_progress.read",
    "providers.special_models.discover",
    "sedentary.read",
    "settings.display_language.read",
    "settings.display_language.update",
    "settings.open_path",
    "settings.state.read",
    "settings.update",
    "system.air_quality.read",
    "system.detection.toggle",
    "system.locale.read",
    "system.media.latest.read",
    "system.media.open_folder",
    "system.statistics.read",
    "system.status.read",
    "usage.read",
    "window.title_bar_theme.update",
    "onboarding.complete",
    "onboarding.legacy_root.pick",
    "onboarding.state.read",
}

FRONTEND_PLUMBING_ROUTES = {
    "/api/v1/camera/stream",
}


def _normalized_route(path):
    path = path.split("?", maxsplit=1)[0]
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path.rstrip("/") or "/"


def _frontend_api_routes():
    route_pattern = re.compile(r"[`'\"](/api/[^`'\"\s]+)")
    source_root = REPOSITORY_ROOT / "src" / "webapp" / "src"
    routes = set()
    for source_file in source_root.rglob("*"):
        if source_file.suffix not in {".js", ".jsx", ".cjs", ".mjs"}:
            continue
        if ".test." in source_file.name:
            continue
        source = source_file.read_text(encoding="utf-8")
        routes.update(
            _normalized_route(match.group(1))
            for match in route_pattern.finditer(source)
            # The transport validates this namespace prefix; it is not an endpoint.
            if _normalized_route(match.group(1)) != "/api/v1"
        )
    return routes


def _frontend_backend_calls():
    call_pattern = re.compile(
        r"fetchBackend(?:Json|Blob)?\(\s*(?P<quote>['\"`])"
        r"(?P<path>/api/[^'\"`]+)(?P=quote)(?P<options>[^)]*)\)",
        re.DOTALL,
    )
    source_root = REPOSITORY_ROOT / "src" / "webapp" / "src"
    calls = set()
    for source_file in source_root.rglob("*"):
        if source_file.suffix not in {".js", ".jsx", ".cjs", ".mjs"}:
            continue
        if ".test." in source_file.name:
            continue
        source = source_file.read_text(encoding="utf-8")
        for match in call_pattern.finditer(source):
            method_match = re.search(
                r"\bmethod\s*:\s*['\"]([A-Za-z]+)['\"]",
                match.group("options"),
            )
            method = method_match.group(1).upper() if method_match else "GET"
            calls.add((method, _normalized_route(match.group("path"))))
    return calls


def test_catalog_names_are_stable_unique_and_lookupable():
    names = [operation.name for operation in OPERATIONS]

    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_OPERATION_NAMES
    assert all(get_operation(name).name == name for name in names)
    with pytest.raises(KeyError):
        get_operation("missing.operation")


def test_every_operation_has_a_valid_schema_and_one_resolvable_source():
    for operation in OPERATIONS:
        assert operation.description.strip()
        assert operation.output_kind in {"json", "text", "stream", "file"}
        assert isinstance(operation.input_schema, dict)
        assert operation.input_schema.get("type") == "object"
        properties = operation.input_schema.get("properties", {})
        required = operation.input_schema.get("required", [])
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert set(required) <= set(properties)
        assert operation.dispatchable or operation.source_ipc_channel
        assert bool(operation.method) == bool(operation.path)
        assert operation.method is None or operation.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert isinstance(operation.mutation, bool)
        assert isinstance(operation.stream, bool)
        assert isinstance(operation.download, bool)
        assert isinstance(operation.side_effect, bool)
        assert isinstance(operation.sensitive, bool)
        assert isinstance(operation.desktop_only, bool)
        assert isinstance(operation.required_headers, dict)
        assert operation.availability in {"available", "backend_bridge_required", "desktop_only"}
        assert isinstance(operation.multipart_file_fields, dict)
        if operation.availability == "available":
            assert operation.dispatchable is True
            assert operation.dispatch_kind in {"http", "config"}
        else:
            assert operation.dispatchable is False
            assert operation.dispatch_kind == "unavailable"
            assert operation.unavailable_reason.strip()
        if operation.stream:
            assert operation.output_kind == "stream"
        if operation.download:
            assert operation.output_kind == "file"


def test_catalog_api_routes_exist_and_cover_every_frontend_api_call():
    from src import server

    # OpenAPI traverses included routers and validates the actual composition.
    server_routes = {
        (method.upper(), _normalized_route(path))
        for path, operations in server.app.openapi()["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    }
    catalog_routes = {
        (operation.method, _normalized_route(operation.path))
        for operation in OPERATIONS
        if operation.method
    }

    assert catalog_routes <= server_routes
    frontend_routes = _frontend_api_routes()
    catalog_paths = {path for _method, path in catalog_routes}
    assert frontend_routes - FRONTEND_PLUMBING_ROUTES <= catalog_paths
    assert frontend_routes & FRONTEND_PLUMBING_ROUTES == FRONTEND_PLUMBING_ROUTES
    assert ("POST", "/api/v1/camera/frame") not in catalog_routes
    assert "/api/v1/camera/frame" not in {operation.path for operation in OPERATIONS}
    assert "/api/v1/camera/stream" not in {operation.path for operation in OPERATIONS}
    assert "/api/v1/media/image" not in {operation.path for operation in OPERATIONS}
    assert "/api/v1/action-plan/source-revision" in {operation.path for operation in OPERATIONS}


def test_catalog_http_methods_match_frontend_calls_on_shared_routes():
    frontend_calls = _frontend_backend_calls()
    duplicated_frontend_calls = {
        (method, path)
        for method, path in frontend_calls
        if path in {
            "/api/v1/chat/context",
            "/api/v1/finance/purchase-recommendations/dismissed",
            "/api/v1/finance/purchase-recommendations/dismissed/{}",
        }
    }
    catalog_calls = {
        (operation.method, _normalized_route(operation.path))
        for operation in OPERATIONS
        if operation.method
    }
    catalog_calls_by_name = {
        operation.name: (operation.method, _normalized_route(operation.path))
        for operation in OPERATIONS
        if operation.method
    }

    assert duplicated_frontend_calls == {
        ("GET", "/api/v1/chat/context"),
        ("DELETE", "/api/v1/chat/context"),
        ("GET", "/api/v1/finance/purchase-recommendations/dismissed"),
        ("DELETE", "/api/v1/finance/purchase-recommendations/dismissed"),
        ("DELETE", "/api/v1/finance/purchase-recommendations/dismissed/{}"),
    }
    assert duplicated_frontend_calls <= catalog_calls
    assert {
        "chat.context.read": catalog_calls_by_name["chat.context.read"],
        "chat.context.reset": catalog_calls_by_name["chat.context.reset"],
        "finance.recommendations.dismissed.list": catalog_calls_by_name[
            "finance.recommendations.dismissed.list"
        ],
        "finance.recommendations.dismissed.clear": catalog_calls_by_name[
            "finance.recommendations.dismissed.clear"
        ],
    } == {
        "chat.context.read": ("GET", "/api/v1/chat/context"),
        "chat.context.reset": ("DELETE", "/api/v1/chat/context"),
        "finance.recommendations.dismissed.list": (
            "GET",
            "/api/v1/finance/purchase-recommendations/dismissed",
        ),
        "finance.recommendations.dismissed.clear": (
            "DELETE",
            "/api/v1/finance/purchase-recommendations/dismissed",
        ),
    }


def test_catalog_covers_electron_invoke_operations_without_renderer_transport():
    preload_source = (REPOSITORY_ROOT / "src" / "webapp" / "preload.cjs").read_text(encoding="utf-8")
    invoked_channels = set(re.findall(r"ipcRenderer\.invoke\('([^']+)'", preload_source))
    catalog_channels = {
        operation.source_ipc_channel
        for operation in OPERATIONS
        if operation.source_ipc_channel
    }

    transport_channels = {"backend:wait-until-ready", "backend:configuration-request", "platform:apply-saved-preferences"}
    assert invoked_channels == catalog_channels | transport_channels
    assert not any("camera:" in channel for channel in catalog_channels)


def test_catalog_marks_streams_downloads_and_mutations_explicitly():
    chat = get_operation("chat.send")
    action_plan = get_operation("action_plan.jobs.create")
    action_plan_events = get_operation("action_plan.jobs.events")
    export = get_operation("face.export")
    model_discovery = get_operation("models.discover")

    assert (chat.output_kind, chat.stream, chat.mutation) == ("stream", True, True)
    assert (action_plan.output_kind, action_plan.stream, action_plan.mutation) == ("json", False, True)
    assert (action_plan_events.output_kind, action_plan_events.stream, action_plan_events.mutation) == ("stream", True, False)
    assert (export.output_kind, export.download, export.mutation) == ("file", True, True)
    assert model_discovery.mutation is False


def test_local_open_folder_intent_and_native_desktop_operations_are_explicit():
    open_folder = get_operation("system.media.open_folder")
    picker = get_operation("onboarding.legacy_root.pick")

    assert open_folder.required_headers == {"X-Vantage-Intent": "open-folder"}
    assert open_folder.side_effect is True
    assert picker.desktop_only is True
    assert picker.source_ipc_channel == "platform:pick-legacy-root"


def test_sensitive_user_data_operations_are_marked_sensitive():
    sensitive_operations = {
        "action_plan.today.read",
        "chat.context.read",
        "finance.balance_sheet.read",
        "face.report.read",
        "media.transcribe",
        "settings.update",
        "system.air_quality.read",
        "system.media.latest.read",
    }

    assert all(get_operation(name).sensitive for name in sensitive_operations)


def test_shared_settings_and_onboarding_operations_are_dispatchable_but_native_actions_are_not():
    backend_operations = {
        "settings.state.read": ("GET", "/api/v1/settings"),
        "settings.update": ("PUT", "/api/v1/settings"),
        "settings.display_language.read": ("GET", "/api/v1/settings/display-language"),
        "settings.display_language.update": ("PUT", "/api/v1/settings/display-language"),
        "onboarding.state.read": ("GET", "/api/v1/onboarding"),
        "onboarding.complete": ("POST", "/api/v1/onboarding/complete"),
    }
    desktop_only_operations = {
        "settings.open_path",
        "system.locale.read",
        "window.title_bar_theme.update",
        "onboarding.legacy_root.pick",
    }

    for name, target in backend_operations.items():
        operation = get_operation(name)
        assert operation.availability == "available"
        assert operation.dispatchable is True
        assert (operation.method, operation.path) == target
        assert operation.config_handler is None
        assert operation.source_ipc_channel is None
        assert operation.ipc_input_mapping == {}
    for name in desktop_only_operations:
        operation = get_operation(name)
        assert operation.availability == "desktop_only"
        assert operation.desktop_only is True
        assert operation.dispatchable is False
        assert operation.method is None
        assert operation.config_handler is None
        assert operation.source_ipc_channel


def test_configuration_catalog_exposes_canonical_fields_without_ipc_aliases():
    settings = get_operation("settings.update")
    onboarding = get_operation("onboarding.complete")

    for operation in (settings, onboarding):
        assert operation.source_ipc_channel is None
        assert operation.ipc_input_mapping == {}
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", name)
                   for name in operation.input_schema["properties"])

    assert {"display_language", "action_plan_check_interval_minutes", "provider_config"} <= set(
        settings.input_schema["properties"]
    )
    assert "provider" not in settings.input_schema["properties"]
    assert {"selected_provider", "legacy_root", "skip_chat_setup"} <= set(onboarding.input_schema["properties"])

    titlebar = get_operation("window.title_bar_theme.update")
    assert titlebar.source_ipc_channel == "platform:set-title-bar-theme"
    assert titlebar.ipc_input_mapping == {"theme": "$argument"}
    assert titlebar.ipc_argument_style == "single"


def test_transcription_declares_the_multipart_upload_field_adapter():
    operation = get_operation("media.transcribe")

    assert operation.request_media_type == "multipart/form-data"
    assert operation.multipart_file_fields == {"file_path": "file"}


def test_input_schemas_describe_nontrivial_user_facing_arguments():
    chat_schema = get_operation("chat.send").input_schema
    folder_schema = get_operation("system.media.open_folder").input_schema
    restore_schema = get_operation("finance.recommendations.dismissed.restore").input_schema
    transcription_schema = get_operation("media.transcribe").input_schema

    assert chat_schema["required"] == ["message"]
    assert chat_schema["properties"]["message"]["type"] == "string"
    assert folder_schema["required"] == ["type"]
    assert folder_schema["properties"]["type"]["enum"] == ["photo", "screenshot"]
    assert restore_schema["required"] == ["item_id"]
    assert restore_schema["properties"]["item_id"]["type"] == "integer"
    assert transcription_schema["required"] == ["file_path"]
    assert transcription_schema["properties"]["file_path"]["type"] == "string"
    assert get_operation("finance.recommendations.read").input_schema["properties"]["recommendation_count"]["minimum"] == 3
    assert get_operation("finance.recommendations.read").input_schema["properties"]["recommendation_count"]["maximum"] == 30
    settings_properties = get_operation("settings.update").input_schema["properties"]
    onboarding_properties = get_operation("onboarding.complete").input_schema["properties"]
    assert settings_properties["display_language"]["enum"] == ["system", "zh-CN", "en-US"]
    assert settings_properties["theme_mode"]["enum"] == ["auto", "dark", "light"]
    assert onboarding_properties["display_language"]["enum"] == ["system", "zh-CN", "en-US"]


def test_onboarding_schema_requires_legacy_root_when_legacy_import_is_enabled():
    schema = get_operation("onboarding.complete").input_schema

    assert schema["allOf"] == [
        {
            "if": {
                "properties": {"import_legacy_data": {"const": True}},
                "required": ["import_legacy_data"],
            },
            "then": {"required": ["legacy_root"]},
        }
    ]
    assert schema["properties"]["legacy_root"]["minLength"] == 1
    assert schema["properties"]["legacy_root"]["pattern"] == r"\S"


def test_provider_config_schema_describes_multi_provider_settings_payload():
    provider_config = get_operation("settings.update").input_schema["properties"]["provider_config"]
    assert provider_config["type"] == "object"
    assert "required" not in provider_config
    assert "omitted top-level members" in provider_config["description"]
    assert "replaces the complete provider set" in provider_config["description"]
    assert provider_config["properties"]["selected_provider"]["type"] == ["string", "null"]
    providers = provider_config["properties"]["providers"]
    assert providers["type"] == "object"
    entry = providers["additionalProperties"]
    assert entry["type"] == "object"
    assert "required" not in entry
    properties = entry["properties"]
    assert properties["route"]["type"] == "string"
    assert properties["enabled"]["type"] == "boolean"
    assert properties["api_key"]["writeOnly"] is True
    assert properties["base_url"]["type"] == "string"
    assert properties["model"]["type"] == "string"
    assert properties["models"]["items"]["type"] == "string"
    assert properties["context_window_tokens"]["type"] == "integer"
    assert properties["context_window_tokens"]["minimum"] == 1
    assert properties["max_output_tokens"]["type"] == "integer"
    assert properties["max_output_tokens"]["minimum"] == 1


def test_settings_update_description_documents_partial_provider_config_semantics():
    description = get_operation("settings.update").description

    assert "omitted top-level members retain existing values" in description
    assert "providers map replaces the complete provider set" in description


def test_settings_schema_accepts_nullable_model_refresh_timestamps():
    settings_properties = get_operation("settings.update").input_schema["properties"]
    for key in (
        "voice_last_refreshed_at",
        "image_last_refreshed_at",
    ):
        assert settings_properties[key]["type"] == ["string", "null"]
    provider_entry = settings_properties["provider_config"]["properties"]["providers"]["additionalProperties"]
    assert provider_entry["properties"]["last_refreshed_at"]["type"] == ["string", "null"]


def test_catalog_descriptors_and_nested_schemas_are_immutable():
    operation = get_operation("chat.send")

    with pytest.raises(FrozenInstanceError):
        operation.name = "chat.changed"
    with pytest.raises(TypeError):
        operation.input_schema["type"] = "string"
    with pytest.raises(TypeError):
        operation.input_schema["properties"]["message"]["type"] = "integer"
    with pytest.raises(TypeError):
        get_operation("system.media.open_folder").required_headers["X-Vantage-Intent"] = "other"


def test_catalog_input_schemas_remain_json_serializable():
    for operation in OPERATIONS:
        round_trip = json.loads(json.dumps(operation.input_schema))
        assert round_trip == operation.input_schema
