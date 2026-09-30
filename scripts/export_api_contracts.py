"""Export stable client DTO schemas without starting hardware or the API server.

Run from the repository root: python -m scripts.export_api_contracts
"""
import json
from pathlib import Path

from src.backend.api_contracts import (
    API_VERSION, ActionPlanJob, ActionPlanJobRequest, ActionPlanJobs, ActionPlanResult,
    ActionPlanStreamEvent, BackendCapabilities, SettingsState, OnboardingState,
    OnboardingCompletion, DisplayLanguageState, ChatContextResponse, ChatRequest,
    ChatStreamEvent, SchedulerState, ConfigurationErrorResponse, ContextErrorResponse,
)
from src.services.automation_catalog import get_operation


def contracts():
    schemas = {model.__name__: model.model_json_schema() for model in (
        ActionPlanJobRequest, ActionPlanJob, ActionPlanJobs, ActionPlanResult,
        ActionPlanStreamEvent, BackendCapabilities, SettingsState, OnboardingState,
        OnboardingCompletion, DisplayLanguageState, ChatContextResponse, ChatRequest,
        ChatStreamEvent, SchedulerState, ConfigurationErrorResponse, ContextErrorResponse,
    )}
    for name, operation in {
        "SettingsUpdateRequest": "settings.update",
        "DisplayLanguageUpdateRequest": "settings.display_language.update",
        "OnboardingCompleteRequest": "onboarding.complete",
    }.items():
        schemas[name] = json.loads(json.dumps(get_operation(operation).input_schema))
    return {"api_version": API_VERSION, "schemas": schemas}


def main():
    target = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "application-v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contracts(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
