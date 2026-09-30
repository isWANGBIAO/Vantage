"""Export stable client DTO schemas without starting hardware or the API server.

Run from the repository root: python -m scripts.export_api_contracts
"""
import json
from pathlib import Path

from src.backend.api_contracts import API_VERSION, ActionPlanJob, ActionPlanJobRequest, BackendCapabilities


def contracts():
    return {
        "api_version": API_VERSION,
        "schemas": {model.__name__: model.model_json_schema()
                    for model in (ActionPlanJobRequest, ActionPlanJob, BackendCapabilities)},
    }


def main():
    target = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "application-v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contracts(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
