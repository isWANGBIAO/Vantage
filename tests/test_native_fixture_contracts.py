"""Smoke fixtures must obey the real API, not a client-specific invented shape."""

import json
import urllib.request

import pytest

from src.backend.api_contracts import (
    ActionPlanJob, ActionPlanJobs, ActionPlanResult, ActionPlanStreamEvent,
    BackendCapabilities, ChatContextResponse, ChatStreamEvent, OnboardingState,
    SchedulerState, SettingsState,
)
from src.native.testing.fixture_backend import start_fixture


@pytest.fixture
def backend():
    server = start_fixture()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()


def request(base, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
        return response.read()


@pytest.mark.parametrize(("path", "model"), [
    ("/api/v1/settings", SettingsState),
    ("/api/v1/onboarding", OnboardingState),
    ("/api/v1/capabilities", BackendCapabilities),
    ("/api/v1/action-plan/today", ActionPlanResult),
    ("/api/v1/action-plan/scheduler", SchedulerState),
    ("/api/v1/action-plan/jobs", ActionPlanJobs),
    ("/api/v1/chat/context", ChatContextResponse),
])
def test_fixture_reads_match_real_dtos(backend, path, model):
    model.model_validate_json(request(backend, path))


def test_fixture_job_creation_and_stream_match_real_dtos(backend):
    job = ActionPlanJob.model_validate_json(request(backend, "/api/v1/action-plan/jobs", {}))
    records = request(backend, f"/api/v1/action-plan/jobs/{job.id}/events?after=0").splitlines()
    assert records
    for record in records:
        ActionPlanStreamEvent.model_validate_json(record)
    snapshot = ActionPlanJob.model_validate_json(request(backend, f"/api/v1/action-plan/jobs/{job.id}"))
    assert snapshot.status == "succeeded"
    assert snapshot.result is not None and snapshot.result.exists


def test_fixture_chat_stream_matches_real_dtos(backend):
    records = request(backend, "/api/v1/chat", {"message": "Synthetic message"}).splitlines()
    for record in records:
        ChatStreamEvent.model_validate_json(record)
    assert json.loads(records[-1]) == {"done": True}
