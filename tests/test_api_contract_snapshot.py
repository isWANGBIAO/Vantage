import json
from pathlib import Path

from scripts.export_api_contracts import contracts


def test_checked_in_native_client_contract_matches_runtime_models():
    path = Path(__file__).resolve().parents[1] / "docs/contracts/application-v1.json"
    assert json.loads(path.read_text(encoding="utf-8")) == contracts()
