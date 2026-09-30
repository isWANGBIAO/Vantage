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


class ActionPlanResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    exists: bool
    analysis: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    date: str | None = None
    filename: str | None = None
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
