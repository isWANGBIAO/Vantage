"""Shared descriptions of user-facing Vantage automation operations.

The catalog is intentionally declarative: it names the existing HTTP, shared
configuration, and narrow Electron bridge boundaries without reimplementing
their behavior. CLI and MCP entry points can use the same stable names and
JSON Schemas while the application remains the source of business rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

from src.core.user_config import MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES


OutputKind = Literal["json", "text", "stream", "file"]
Availability = Literal["available", "backend_bridge_required", "desktop_only"]

_DESKTOP_ONLY_REASON = (
    "This action requires a native platform adapter and cannot be invoked "
    "through the backend API."
)


class _FrozenDict(dict):
    """A JSON-serializable dict that rejects normal mutation attempts."""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("catalog schemas are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    """A JSON-serializable list that rejects normal mutation attempts."""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("catalog schemas are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze(item) for item in value)
    return value


def _object_schema(
    properties: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
    one_of: tuple[Mapping[str, Any], ...] = (),
    all_of: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    if one_of:
        schema["oneOf"] = list(one_of)
    if all_of:
        schema["allOf"] = list(all_of)
    return schema


def _string(description: str, *, enum: tuple[str, ...] | None = None, write_only: bool = False):
    schema: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        schema["enum"] = list(enum)
    if write_only:
        schema["writeOnly"] = True
    return schema


def _nullable_string(description: str):
    return {"type": ["string", "null"], "description": description}


def _boolean(description: str):
    return {"type": "boolean", "description": description}


def _integer(description: str, *, minimum: int | None = None, maximum: int | None = None):
    schema: dict[str, Any] = {"type": "integer", "description": description}
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def _number(description: str, *, minimum: float | None = None):
    schema: dict[str, Any] = {"type": "number", "description": description}
    if minimum is not None:
        schema["minimum"] = minimum
    return schema


def _array_of_strings(description: str):
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string"},
    }


def _provider_entry_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "route": _string("Stable provider route identifier."),
            "name": _string("User-facing provider name."),
            "type": _string("Provider protocol type.", enum=("openai-compatible",)),
            "enabled": _boolean("Whether this provider may be selected."),
            "api_key": _string("Write-only provider key; omission or masking preserves it only at the same destination, and an explicit empty value clears it.", write_only=True),
            "base_url": _string("Provider API base URL."),
            "model": _string("Default model identifier."),
            "models": _array_of_strings("Known model identifiers for this provider."),
            "last_refreshed_at": _nullable_string("Timestamp of the last model catalog refresh, or null if it has not been refreshed."),
            "context_window_tokens": _integer("Optional provider context-window capacity in tokens.", minimum=1),
            "max_output_tokens": _integer("Optional provider maximum output-token limit.", minimum=1),
        },
    }


def _provider_model_profile_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "parameters": {
                "type": "object",
                "additionalProperties": {"type": ["number", "string", "boolean"]},
            },
            "omit_parameters": _array_of_strings("Sampling parameter names omitted for this model."),
            "extra": {"type": "object", "additionalProperties": True},
            "max_tokens": _integer("Optional model output-token limit.", minimum=1),
            "reasoning_tiers": _array_of_strings("Reasoning levels supported by this model."),
            "reasoning_aliases": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


def _provider_config_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Partial provider configuration update. Omitted top-level members retain their existing values. "
            "If providers is omitted, existing providers are kept; a supplied providers map replaces the complete "
            "provider set (including an empty map to remove all providers). API keys are write-only."
        ),
        "additionalProperties": False,
        "properties": {
            "version": _integer("Provider-configuration schema version.", minimum=1),
            "selected_provider": {"type": ["string", "null"]},
            "sampling_defaults": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "temperature": _number("Default model temperature."),
                    "top_p": _number("Default nucleus-sampling probability."),
                    "top_k": _integer("Default top-k sampling count.", minimum=1),
                    "presence_penalty": _number("Default presence penalty."),
                    "repetition_penalty": _number("Default repetition penalty."),
                },
            },
            "model_profiles": {
                "type": "object",
                "additionalProperties": _provider_model_profile_schema(),
            },
            "providers": {
                "type": "object",
                "additionalProperties": _provider_entry_schema(),
            },
        },
    }


@dataclass(frozen=True, slots=True)
class Operation:
    """One stable product operation and its existing implementation boundary."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_kind: OutputKind
    method: str | None = None
    path: str | None = None
    config_handler: str | None = None
    source_ipc_channel: str | None = None
    availability: Availability = "available"
    unavailable_reason: str | None = None
    ipc_input_mapping: Mapping[str, str] = field(default_factory=dict)
    ipc_argument_style: Literal["object", "single"] = "object"
    request_media_type: str | None = None
    multipart_file_fields: Mapping[str, str] = field(default_factory=dict)
    mutation: bool = False
    stream: bool = False
    download: bool = False
    side_effect: bool = False
    sensitive: bool = False
    desktop_only: bool = False
    required_headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name or not self.description.strip():
            raise ValueError("catalog operations require a name and description")
        if bool(self.method) != bool(self.path):
            raise ValueError("HTTP operations must define both method and path")
        if self.method and self.method != self.method.upper():
            raise ValueError("HTTP methods must be uppercase")
        if self.availability == "available":
            targets = sum(bool(value) for value in (self.method, self.config_handler))
            if targets != 1:
                raise ValueError("available operations require exactly one HTTP or config target")
            if self.unavailable_reason:
                raise ValueError("available operations cannot have an unavailable reason")
        else:
            if self.method or self.path or self.config_handler:
                raise ValueError("unavailable operations cannot claim a dispatch target")
            if not self.source_ipc_channel or not self.unavailable_reason:
                raise ValueError("unavailable Electron operations require a source channel and reason")
        if self.availability == "desktop_only" and not self.desktop_only:
            raise ValueError("desktop-only operations must be marked desktop_only")
        if self.availability == "backend_bridge_required" and self.desktop_only:
            raise ValueError("backend bridge operations cannot be marked desktop_only")
        if self.stream and self.output_kind != "stream":
            raise ValueError("streaming operations must use the stream output kind")
        if self.download and self.output_kind != "file":
            raise ValueError("download operations must use the file output kind")
        if self.multipart_file_fields and self.request_media_type != "multipart/form-data":
            raise ValueError("multipart file fields require multipart/form-data request metadata")
        schema_properties = self.input_schema.get("properties", {})
        if set(self.multipart_file_fields) - set(schema_properties):
            raise ValueError("multipart file fields must be declared in the input schema")
        if set(self.ipc_input_mapping) - set(schema_properties):
            raise ValueError("IPC input mappings must refer to declared schema properties")
        object.__setattr__(self, "input_schema", _freeze(self.input_schema))
        object.__setattr__(self, "ipc_input_mapping", _freeze(self.ipc_input_mapping))
        object.__setattr__(self, "multipart_file_fields", _freeze(self.multipart_file_fields))
        object.__setattr__(self, "required_headers", _freeze(self.required_headers))

    @property
    def dispatchable(self) -> bool:
        return self.availability == "available" and bool(self.method or self.config_handler)

    @property
    def dispatch_kind(self) -> Literal["http", "config", "unavailable"]:
        if not self.dispatchable:
            return "unavailable"
        if self.method:
            return "http"
        return "config"


_EMPTY = _object_schema()


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        name="system.capabilities.read", description="Discover the versioned backend API and platform-owned capabilities.",
        method="GET", path="/api/v1/capabilities", input_schema=_EMPTY, output_kind="json",
    ),
    Operation(
        name="action_plan.source_revision.read", description="Read the action-plan source fingerprint without generating content.",
        method="GET", path="/api/v1/action-plan/source-revision", input_schema=_EMPTY, output_kind="json",
    ),
    Operation(
        name="action_plan.jobs.create", description="Start or join the single backend-owned action-plan job. Disconnecting does not cancel it.",
        method="POST", path="/api/v1/action-plan/jobs",
        input_schema=_object_schema({
            "reasoning_effort": _string("Optional reasoning effort."),
            "service_tier": _string("Optional service tier."),
            "model": _string("Optional configured model."),
            "provider_route": _string("Optional configured provider route."),
            "replace_today": _boolean("Replace existing plans only after a new complete result is saved."),
            "wait_for_provider_ready": _boolean("Wait for the configured local provider to become ready."),
        }), output_kind="json", mutation=True, sensitive=True, side_effect=True,
    ),
    Operation(
        name="action_plan.jobs.list", description="Read retained action-plan jobs and the shared active job.",
        method="GET", path="/api/v1/action-plan/jobs", input_schema=_EMPTY, output_kind="json", sensitive=True,
    ),
    Operation(
        name="action_plan.jobs.read", description="Read one backend-owned action-plan job, including its terminal result or error.",
        method="GET", path="/api/v1/action-plan/jobs/{job_id}",
        input_schema=_object_schema({"job_id": _string("Job identifier returned by create/list.")}, required=("job_id",)),
        output_kind="json", sensitive=True,
    ),
    Operation(
        name="action_plan.jobs.events", description="Observe job NDJSON events after a sequence cursor. A truncated event requires a status/result reload.",
        method="GET", path="/api/v1/action-plan/jobs/{job_id}/events",
        input_schema=_object_schema({"job_id": _string("Job identifier."), "after": _integer("Last received event sequence.", minimum=0)}, required=("job_id",)),
        output_kind="stream", stream=True, sensitive=True,
    ),
    Operation(
        name="action_plan.jobs.cancel", description="Explicitly cancel a backend job and wait for its generation process cleanup.",
        method="POST", path="/api/v1/action-plan/jobs/{job_id}/cancel",
        input_schema=_object_schema({"job_id": _string("Job identifier to cancel.")}, required=("job_id",)),
        output_kind="json", mutation=True, sensitive=True,
    ),
    Operation(
        name="action_plan.scheduler.read", description="Read backend-owned automatic generation and source-check status.",
        method="GET", path="/api/v1/action-plan/scheduler", input_schema=_EMPTY, output_kind="json",
    ),
    Operation(
        name="system.status.read",
        description="Read Vantage service and camera status, including detection visibility.",
        method="GET",
        path="/api/v1/system/status",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="system.statistics.read",
        description="Read current CPU, memory, disk-free, and Vantage media-storage statistics.",
        method="GET",
        path="/api/v1/system/statistics",
        input_schema=_EMPTY,
        output_kind="json",
    ),
    Operation(
        name="system.detection.toggle",
        description="Toggle the camera person-box overlay in the running Vantage backend.",
        method="POST",
        path="/api/v1/camera/detection/toggle",
        input_schema=_EMPTY,
        output_kind="json",
        mutation=True,
        side_effect=True,
        sensitive=True,
    ),
    Operation(
        name="system.media.open_folder",
        description="Open the configured photo or screenshot folder in the operating system file manager.",
        method="POST",
        path="/api/v1/media/open-folder",
        input_schema=_object_schema(
            {"type": _string("Configured media folder to open.", enum=("photo", "screenshot"))},
            required=("type",),
        ),
        output_kind="json",
        side_effect=True,
        sensitive=True,
        required_headers={"X-Vantage-Intent": "open-folder"},
    ),
    Operation(
        name="system.air_quality.read",
        description="Read current AQI for a trusted current location. Supplied browser coordinates are validated against the local location trust policy.",
        method="GET",
        path="/api/v1/system/air-quality",
        input_schema=_object_schema({
            "lat": _number("Optional latitude from the current browser location."),
            "lon": _number("Optional longitude from the current browser location."),
            "accuracy": _number("Optional browser location accuracy in meters.", minimum=0),
            "timestamp_ms": _number("Optional browser location capture time in Unix milliseconds.", minimum=0),
        }),
        output_kind="json",
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="system.media.latest.read",
        description="Read the latest captured photo and screenshot references and scan status.",
        method="GET",
        path="/api/v1/media/latest",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="sedentary.read",
        description="Read the current presence-confidence and sedentary timer state.",
        method="GET",
        path="/api/v1/health/sedentary",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="plots.refresh",
        description="Clear the dashboard plot cache so the next plot read rebuilds it from current data.",
        method="POST",
        path="/api/v1/plots/refresh",
        input_schema=_EMPTY,
        output_kind="json",
        mutation=True,
    ),
    Operation(
        name="plots.read",
        description="Read the current dashboard plot data.",
        method="GET",
        path="/api/v1/plots/data",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="action_plan.today.read",
        description="Read today's latest saved action plan, including analysis, plan, metadata, and whether it exists.",
        method="GET",
        path="/api/v1/action-plan/today",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="chat.context.read",
        description="Read the current chat context summary, action-plan context flag, and usage metadata.",
        method="GET",
        path="/api/v1/chat/context",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="chat.context.reset",
        description="Reset the latest chat context while preserving the action-plan context.",
        method="DELETE",
        path="/api/v1/chat/context",
        input_schema=_EMPTY,
        output_kind="json",
        mutation=True,
        sensitive=True,
    ),
    Operation(
        name="usage.read",
        description="Read usage and token-cost summaries from the local history database.",
        method="GET",
        path="/api/v1/usage",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="models.list",
        description="List configured providers and available model options for chat and action plans.",
        method="GET",
        path="/api/v1/models",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="providers.special_models.discover",
        description="Discover voice or image models using the selected or supplied special-provider configuration.",
        method="POST",
        path="/api/v1/providers/models/discover",
        input_schema=_object_schema({
            "kind": _string("Special provider to inspect.", enum=("voice", "image")),
            "mode": _string("Use a custom provider or inherit the active AI provider.", enum=("custom", "inherit_ai")),
            "route": _string("Optional configured provider route."),
            "base_url": _string("Optional provider API base URL."),
            "api_key": _string("Optional provider API key; a saved key can be reused.", write_only=True),
            "type": _string("Provider protocol type, such as openai-compatible."),
        }),
        output_kind="json",
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="models.discover",
        description="Discover models from a configured provider or an explicitly supplied compatible endpoint.",
        method="POST",
        path="/api/v1/models/discover",
        input_schema=_object_schema({
            "route": _string("Optional configured provider route."),
            "base_url": _string("Optional provider API base URL."),
            "api_key": _string("Optional provider API key; a saved key can be reused.", write_only=True),
            "type": _string("Provider protocol type, such as openai-compatible."),
        }),
        output_kind="json",
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="chat.send",
        description="Send a chat message through the configured model provider and return its NDJSON response stream.",
        method="POST",
        path="/api/v1/chat",
        input_schema=_object_schema({
            "message": _string("User message to send."),
            "model": _string("Optional model identifier."),
            "provider_route": _string("Optional configured provider route."),
            "context_file": _string("Optional context file; only Vantage's configured latest chat context is accepted."),
            "reasoning_effort": _string("Optional reasoning effort.", enum=("low", "medium", "high", "xhigh", "max")),
            "service_tier": _string("Optional provider service tier.", enum=("priority", "fast")),
            "client_sent_at": _string("Optional client timestamp associated with the message."),
        }, required=("message",)),
        output_kind="stream",
        mutation=True,
        stream=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="media.transcribe",
        description="Transcribe a local audio file using the configured voice provider; the audio is uploaded only for this transcription request.",
        method="POST",
        path="/api/v1/media/transcribe",
        input_schema=_object_schema({
            "file_path": {
                "type": "string",
                "description": "Path to the local audio file to transcribe.",
                "format": "path",
                "contentMediaType": "audio/*",
            },
        }, required=("file_path",)),
        output_kind="json",
        request_media_type="multipart/form-data",
        multipart_file_fields={"file_path": "file"},
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="logs.read",
        description="Read the most recent server log lines from the configured runtime log file.",
        method="GET",
        path="/api/v1/system/logs",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="finance.recommendations.read",
        description="Read purchase recommendations for the current balance sheet, generating and caching them if needed.",
        method="GET",
        path="/api/v1/finance/purchase-recommendations",
        input_schema=_object_schema({
            "recommendation_count": _integer("Optional number of recommendations to request; values are normalized to the supported range.", minimum=3, maximum=30),
            "model": _string("Optional model identifier."),
            "provider_route": _string("Optional configured provider route."),
            "reasoning_effort": _string("Optional reasoning effort.", enum=("low", "medium", "high", "xhigh", "max")),
            "service_tier": _string("Optional provider service tier.", enum=("priority", "fast")),
        }),
        output_kind="json",
        mutation=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="finance.recommendations.regenerate",
        description="Regenerate purchase recommendations from the current balance sheet and save the new result.",
        method="POST",
        path="/api/v1/finance/purchase-recommendations/regenerate",
        input_schema=_object_schema({
            "recommendation_count": _integer("Optional number of recommendations to request; values are normalized to the supported range.", minimum=3, maximum=30),
            "model": _string("Optional model identifier."),
            "provider_route": _string("Optional configured provider route."),
            "reasoning_effort": _string("Optional reasoning effort.", enum=("low", "medium", "high", "xhigh", "max")),
            "service_tier": _string("Optional provider service tier.", enum=("priority", "fast")),
        }),
        output_kind="json",
        mutation=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="finance.recommendations.dismiss",
        description="Dismiss one purchase recommendation so it is hidden from the active recommendation view.",
        method="POST",
        path="/api/v1/finance/purchase-recommendations/dismiss",
        input_schema=_object_schema({
            "cache_key": _string("Optional recommendation cache key."),
            "group_key": _string("Optional recommendation group key."),
            "item": {"type": "object", "description": "Recommendation item to dismiss."},
        }),
        output_kind="json",
        mutation=True,
        sensitive=True,
    ),
    Operation(
        name="finance.recommendations.dismissed.list",
        description="List purchase recommendations that have been dismissed.",
        method="GET",
        path="/api/v1/finance/purchase-recommendations/dismissed",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="finance.recommendations.dismissed.clear",
        description="Restore all dismissed purchase recommendations to the active recommendation view.",
        method="DELETE",
        path="/api/v1/finance/purchase-recommendations/dismissed",
        input_schema=_EMPTY,
        output_kind="json",
        mutation=True,
        sensitive=True,
    ),
    Operation(
        name="finance.recommendations.dismissed.restore",
        description="Restore one dismissed purchase recommendation to the active recommendation view.",
        method="DELETE",
        path="/api/v1/finance/purchase-recommendations/dismissed/{item_id}",
        input_schema=_object_schema({"item_id": _integer("Identifier of the dismissed recommendation.", minimum=1)}, required=("item_id",)),
        output_kind="json",
        mutation=True,
        sensitive=True,
    ),
    Operation(
        name="finance.balance_sheet.read",
        description="Read balance-sheet summaries, suggestions, trends, forecasts, and sheet rows from the configured workbook.",
        method="GET",
        path="/api/v1/finance/balance-sheet",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="face.analyze",
        description="Start background face-history analysis and write the analysis report to Vantage history.",
        method="POST",
        path="/api/v1/face/analyze",
        input_schema=_EMPTY,
        output_kind="json",
        mutation=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="face.live.read",
        description="Read recent live face-presence score points; use active=true to mark the live viewer as visible.",
        method="GET",
        path="/api/v1/face/live",
        input_schema=_object_schema({"active": _boolean("Whether a live viewer is currently active.")}),
        output_kind="json",
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="face.report.read",
        description="Read the latest face-history analysis report and associated chart references.",
        method="GET",
        path="/api/v1/face/report",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="face.export",
        description="Export face-history analysis results to an Excel workbook and return the generated file.",
        method="GET",
        path="/api/v1/face/export",
        input_schema=_EMPTY,
        output_kind="file",
        mutation=True,
        download=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="face.progress.read",
        description="Read current face-history analysis status and completion percentage.",
        method="GET",
        path="/api/v1/face/progress",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="project_progress.read",
        description="Read completed and pending project tasks from the configured project-management source.",
        method="GET",
        path="/api/v1/projects/progress",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="settings.state.read",
        description="Read sanitized Vantage settings, masked provider state, migration state, and configured runtime paths.",
        method="GET",
        path="/api/v1/settings",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="settings.update",
        description=(
            "Update sanitized Vantage settings and provider configuration. In provider_config, omitted top-level "
            "members retain existing values; a supplied providers map replaces the complete provider set "
            "(including an empty map). API-key values are write-only and masked in returned state. CLI/MCP calls "
            "persist settings only; Electron login-item and tray effects are applied only through the desktop UI. "
            "Backend scheduling observes external interval changes without a UI reload."
        ),
        input_schema=_object_schema({
            "display_language": _string("Display language preference.", enum=("system", "zh-CN", "en-US")),
            "theme": _string("Window theme.", enum=("light", "dark")),
            "theme_mode": _string("Theme selection mode.", enum=("auto", "dark", "light")),
            "launch_at_login": _boolean("Start Vantage after Windows login when supported."),
            "action_plan_auto_generate": _boolean("Enable automatic action-plan generation."),
            "action_plan_check_interval_minutes": _integer(
                "Automatic action-plan check interval in minutes (0 disables it).",
                minimum=0,
                maximum=MAX_ACTION_PLAN_CHECK_INTERVAL_MINUTES,
            ),
            "voice_provider_mode": _string("Voice provider selection mode.", enum=("custom", "inherit_ai")),
            "voice_base_url": _string("Voice provider API base URL."),
            "voice_api_key": _string("Voice provider API key.", write_only=True),
            "voice_model": _string("Voice transcription model identifier."),
            "voice_models": _array_of_strings("Available voice model identifiers."),
            "voice_last_refreshed_at": _nullable_string("Timestamp of the last voice-model catalog refresh, or null if it has not been refreshed."),
            "image_provider_mode": _string("Image provider selection mode.", enum=("custom", "inherit_ai")),
            "image_base_url": _string("Image provider API base URL."),
            "image_api_key": _string("Image provider API key.", write_only=True),
            "image_model": _string("Image model identifier."),
            "image_models": _array_of_strings("Available image model identifiers."),
            "image_last_refreshed_at": _nullable_string("Timestamp of the last image-model catalog refresh, or null if it has not been refreshed."),
            "provider_config": {
                **_provider_config_schema(),
                "description": (
                    "Optional partial provider configuration; omitted top-level members retain existing values. "
                    "If providers is omitted, existing providers are kept; a supplied providers map replaces the "
                    "complete provider set. API keys are write-only."
                ),
            },
        }),
        method="PUT",
        path="/api/v1/settings",
        output_kind="json",
        mutation=True,
        sensitive=True,
        side_effect=True,
    ),
    Operation(
        name="settings.open_path",
        description="Open one allowlisted Vantage data or runtime directory in the operating system file manager.",
        input_schema=_object_schema({
            "path_key": _string("Allowlisted Vantage directory key.", enum=("config", "history", "logs", "plots", "cache", "runtime", "data"))
        }, required=("path_key",)),
        output_kind="json",
        source_ipc_channel="platform:open-settings-path",
        availability="desktop_only",
        unavailable_reason=_DESKTOP_ONLY_REASON,
        ipc_input_mapping={"path_key": "$argument"},
        ipc_argument_style="single",
        side_effect=True,
        sensitive=True,
        desktop_only=True,
    ),
    Operation(
        name="settings.display_language.read",
        description="Read the saved display-language preference from shared Vantage settings.",
        method="GET",
        path="/api/v1/settings/display-language",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="settings.display_language.update",
        description=(
            "Persist the Vantage display-language preference. Direct CLI/MCP calls do not refresh Electron tray "
            "labels; that native effect is applied by the desktop UI."
        ),
        input_schema=_object_schema({
            "display_language": _string("Display language preference.", enum=("system", "zh-CN", "en-US"))
        }, required=("display_language",)),
        method="PUT",
        path="/api/v1/settings/display-language",
        output_kind="json",
        mutation=True,
        side_effect=True,
    ),
    Operation(
        name="system.locale.read",
        description="Read the locale reported by the running Electron application.",
        input_schema=_EMPTY,
        output_kind="text",
        source_ipc_channel="platform:get-system-locale",
        availability="desktop_only",
        unavailable_reason=_DESKTOP_ONLY_REASON,
        desktop_only=True,
    ),
    Operation(
        name="window.title_bar_theme.update",
        description="Apply a light or dark native title-bar overlay to the running Windows application window.",
        input_schema=_object_schema({"theme": _string("Native title-bar theme.", enum=("light", "dark"))}, required=("theme",)),
        output_kind="json",
        source_ipc_channel="platform:set-title-bar-theme",
        availability="desktop_only",
        unavailable_reason=_DESKTOP_ONLY_REASON,
        ipc_input_mapping={"theme": "$argument"},
        ipc_argument_style="single",
        side_effect=True,
        desktop_only=True,
    ),
    Operation(
        name="onboarding.state.read",
        description="Read onboarding completion, provider setup, migration state, and the chosen legacy-history source.",
        method="GET",
        path="/api/v1/onboarding",
        input_schema=_EMPTY,
        output_kind="json",
        sensitive=True,
    ),
    Operation(
        name="onboarding.legacy_root.pick",
        description="Open the Electron native directory picker so a user can select the legacy history root; this requires the running desktop UI.",
        input_schema=_EMPTY,
        output_kind="json",
        source_ipc_channel="platform:pick-legacy-root",
        availability="desktop_only",
        unavailable_reason=_DESKTOP_ONLY_REASON,
        side_effect=True,
        sensitive=True,
        desktop_only=True,
    ),
    Operation(
        name="onboarding.complete",
        description=(
            "Complete onboarding after an explicit chat-setup choice, preserving existing providers when chat setup "
            "is skipped and merging configured provider changes. Optionally import history from an explicitly "
            "selected legacy root. CLI/MCP calls persist data only and do not apply Electron login-item or tray effects."
        ),
        input_schema=_object_schema({
            "display_language": _string("Display language preference.", enum=("system", "zh-CN", "en-US")),
            "launch_at_login": _boolean("Start Vantage after Windows login when supported."),
            "selected_provider": {
                **_string("Selected provider route."),
                "minLength": 1,
                "pattern": r"\S",
            },
            "base_url": _string("Provider API base URL."),
            "api_key": _string("Provider API key.", write_only=True),
            "model": _string("Default model identifier."),
            "skip_chat_setup": _boolean("Required explicit choice: true skips chat setup and preserves existing providers; false requires selected_provider."),
            "import_legacy_data": _boolean("Copy missing history/state files from legacy_root into the configured user-data directory; when true, legacy_root is required."),
            "legacy_root": {
                "type": "string",
                "format": "path",
                "description": "Explicit source directory required when legacy-history import is enabled.",
                "minLength": 1,
                "pattern": r"\S",
            },
        }, required=("skip_chat_setup",), one_of=(
            {"properties": {"skip_chat_setup": {"enum": [True]}}},
            {
                "properties": {"skip_chat_setup": {"enum": [False]}},
                "required": ["selected_provider"],
            },
        ), all_of=(
            {
                "if": {
                    "properties": {"import_legacy_data": {"const": True}},
                    "required": ["import_legacy_data"],
                },
                "then": {"required": ["legacy_root"]},
            },
        )),
        method="POST",
        path="/api/v1/onboarding/complete",
        output_kind="json",
        mutation=True,
        sensitive=True,
        side_effect=True,
    ),
)


_operations_by_name = {operation.name: operation for operation in OPERATIONS}
if len(_operations_by_name) != len(OPERATIONS):
    raise ValueError("catalog operation names must be unique")

OPERATION_CATALOG: Mapping[str, Operation] = MappingProxyType(_operations_by_name)


def get_operation(name: str) -> Operation:
    """Return a catalog operation by stable name or raise ``KeyError``."""

    return OPERATION_CATALOG[name]
