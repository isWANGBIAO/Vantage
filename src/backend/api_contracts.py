"""Versioned UI-neutral transport contracts. No desktop/runtime imports."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "1.0"


class ActionPlanJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasoning_effort: str | None = None
    service_tier: str | None = None
    model: str | None = None
    provider_route: str | None = None
    replace_today: bool = False
    wait_for_provider_ready: bool = False


class JobError(BaseModel):
    code: str
    message: str


class JobProgress(BaseModel):
    model_config = ConfigDict(extra="allow")
    phase: str
    events_received: int = 0


class ActionPlanSection(BaseModel):
    model_config = ConfigDict(extra="allow")
    body: str


class ActionPlanMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    generated_at: str | None = None
    model: str | None = None
    provider_route: str | None = None
    requested_model: str | None = None
    requested_provider_route: str | None = None
    fallback_used: bool = False
    reasoning_effort: str | None = None
    input: dict[str, str] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)


class ActionPlanResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    exists: bool
    analysis: ActionPlanSection | None = None
    plan: ActionPlanSection | None = None
    meta: ActionPlanMetadata | None = None
    date: str | None = None
    filename: str | None = None
    timestamp: float | None = None
    error: str | None = None
    id: str | int | None = None


class ActionPlanJob(BaseModel):
    id: str
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    trigger: str
    request: ActionPlanJobRequest
    created_at: str
    updated_at: str
    progress: JobProgress
    result: ActionPlanResult | None = None
    error: JobError | None = None
    source_revision: str | None = None
    result_identity: str | None = None
    event_cursor: int
    reused: bool = False


class ActionPlanJobs(BaseModel):
    jobs: list[ActionPlanJob]
    active: ActionPlanJob | None


class BackendCapabilities(BaseModel):
    api_version: str = API_VERSION
    service: str = "vantage"
    transport: str = "loopback-http"
    capabilities: list[str] = Field(default_factory=list)
    platform_owned: list[str] = Field(default_factory=list)
    contracts_url: str = "/openapi.json"
    operations_url: str = "/api/v1/operations"
    job_retention: str = "process-lifetime, bounded; saved results survive restart"


class ExtensibleModel(BaseModel):
    """Known fields are typed; provider-specific metadata may be additive."""
    model_config = ConfigDict(extra="allow")


class MaskedProvider(ExtensibleModel):
    route: str
    name: str
    type: str
    enabled: bool
    api_key: Literal["", "********"]
    base_url: str
    model: str
    models: list[str]
    last_refreshed_at: str | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None


class ModelProfile(ExtensibleModel):
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    omit_parameters: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    max_tokens: int | None = None
    reasoning_tiers: list[str] = Field(default_factory=list)
    reasoning_aliases: dict[str, str] = Field(default_factory=dict)


class ProviderState(ExtensibleModel):
    version: int
    selected_provider: str | None
    sampling_defaults: dict[str, float | int | str | bool]
    model_profiles: dict[str, ModelProfile]
    providers: dict[str, MaskedProvider]


class SettingsValues(ExtensibleModel):
    version: int
    onboarding_completed: bool
    launch_at_login: bool
    display_language: Literal["system", "zh-CN", "en-US"]
    theme: Literal["dark", "light"]
    theme_mode: Literal["dark", "light", "auto"]
    action_plan_auto_generate: bool
    action_plan_check_interval_minutes: int = Field(ge=0, le=35791)
    voice_provider_mode: Literal["inherit_ai", "custom"]
    voice_base_url: str
    voice_api_key: Literal["", "********"]
    voice_has_api_key: bool
    voice_model: str
    voice_models: list[str]
    voice_last_refreshed_at: str | None
    image_provider_mode: Literal["inherit_ai", "custom"]
    image_base_url: str
    image_api_key: Literal["", "********"]
    image_has_api_key: bool
    image_model: str
    image_models: list[str]
    image_last_refreshed_at: str | None


class MigrationState(ExtensibleModel):
    completed: bool
    source_path: str | None
    imported_at: str | None


class SettingsState(ExtensibleModel):
    settings: SettingsValues
    provider: ProviderState
    migration: MigrationState
    runtime_paths: dict[str, str]


class DisplayLanguageState(BaseModel):
    display_language: Literal["system", "zh-CN", "en-US"]


class OnboardingState(BaseModel):
    completed: bool
    launchAtLogin: bool
    displayLanguage: Literal["system", "zh-CN", "en-US"]
    providerConfigured: bool
    migrationCompleted: bool
    legacyRoot: str | None


class OnboardingMigration(BaseModel):
    imported: bool
    completed: bool
    sourcePath: str | None


class OnboardingPreferences(BaseModel):
    display_language: Literal["system", "zh-CN", "en-US"]
    theme: Literal["dark", "light"]
    theme_mode: Literal["dark", "light", "auto"]
    launch_at_login: bool


class OnboardingProvider(BaseModel):
    selected_provider: str | None
    providers: list[str]


class OnboardingCompletion(BaseModel):
    completed: Literal[True]
    launchAtLogin: bool
    providerConfigured: bool
    migration: OnboardingMigration
    settings: OnboardingPreferences
    provider: OnboardingProvider


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    model: str | None = None
    provider_route: str | None = None
    context_file: str | None = None
    reasoning_effort: str | None = None
    service_tier: str | None = None
    client_sent_at: str | None = None


class VisibleChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatContextResponse(ExtensibleModel):
    base_context_version: str
    context_version: str
    has_action_plan_context: bool
    display_messages: list[VisibleChatMessage]
    messages: list[VisibleChatMessage]
    stats: dict[str, Any] | None = None
    preferred_model: str | None = None
    preferred_provider_route: str | None = None
    preferred_model_option_id: str | None = None


class SchedulerState(BaseModel):
    running: bool
    enabled: bool
    startup_auto_generate: bool
    onboarding_completed: bool
    outcome: str
    error: JobError | None
    check_interval_minutes: int | None
    date: str
    baseline_revision: str | None
    generated_revision: str | None


class StreamLogEvent(ExtensibleModel):
    log: str


class StreamErrorEvent(ExtensibleModel):
    error: str
    error_code: str | None = None


class StreamDoneEvent(ExtensibleModel):
    done: Literal[True]


class JobEventMetadata(ExtensibleModel):
    sequence: int = Field(ge=1)
    timestamp: str


class JobLogEvent(JobEventMetadata):
    log: str


class JobErrorEvent(JobEventMetadata):
    error: str
    error_code: str
    job_status: Literal["failed"]


class JobDoneEvent(JobEventMetadata):
    done: Literal[True]
    job_status: Literal["succeeded"]


class JobStateEvent(JobEventMetadata):
    job_status: Literal["queued", "running", "cancelling", "cancelled"]
    phase: str | None = None


class JobTruncatedEvent(ExtensibleModel):
    truncated: Literal[True]
    cursor: int | None = None
    sequence: int | None = None
    timestamp: str | None = None
    job_status: str | None = None
    event_truncated: bool | None = None


from pydantic import RootModel


class ActionPlanStreamEvent(RootModel[JobLogEvent | JobErrorEvent | JobDoneEvent | JobStateEvent | JobTruncatedEvent]):
    """One JSON object per UTF-8 NDJSON line, never a JSON array."""


class ChatStreamEvent(RootModel[StreamLogEvent | StreamErrorEvent | StreamDoneEvent]):
    """One chat stream record; EOF alone does not confirm completion."""


class ConfigurationErrorResponse(BaseModel):
    code: Literal['configuration_unreadable']
    error: str
    original_preserved: Literal[True]


class ContextErrorDetail(BaseModel):
    code: Literal['CONTEXT_UNREADABLE']
    message: str


class ContextErrorResponse(BaseModel):
    detail: ContextErrorDetail
