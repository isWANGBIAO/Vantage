"""Synthetic API acceptance; never loads a real personal workbook or model."""

import base64
import io
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from src.backend import clothing
from src.services import clothing_vision
from src.services.clothing_models import ClothingRecord
from src.services.clothing_workbook import HEADERS


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / "clothing.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Sheet1"
    book.active.append(HEADERS)
    book.active.append(["Test jacket", "整件反馈未确认", "M", None, None, 110, 70, 44, 55, 60,
                        "2026-01-01", "Example", "STYLE-A", "外壳", "显窄", "合适", "合适", "未记录",
                        "尺码截图（cm，误差1–3cm）；反馈针对整件试穿"])
    book.save(path)
    settings = {"clothing_workbook_path": str(path), "image_model": "configured-vision"}
    monkeypatch.setattr(clothing.user_config, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(clothing.user_config, "save_settings", lambda value: settings.update(value))
    monkeypatch.setattr(clothing, "vision_status", lambda: {"ready": False, "model": "configured-vision", "missing": []})
    app = FastAPI()
    app.include_router(clothing.router)
    return TestClient(app), path, settings


def candidate():
    return {"garment": "Test jacket", "brand": "Example", "style_code": "STYLE-A", "category": "外套",
            "size": "L", "component": "外壳", "chest_cm": 114, "shoulder_cm": 46, "length_cm": 72,
            "length_basis": "后肩衣长", "sleeve_cm": 62, "sleeve_basis": "肩点袖长",
            "measurement_source": "人工核对尺码截图", "measurement_tolerance_cm": 3}


def test_state_compare_and_append_share_one_workbook(api):
    client, path, settings = api
    before = path.read_bytes()
    state = client.get("/api/v1/clothing/state").json()
    assert len(state["records"]) == 1 and not state["vision"]["ready"]
    request = {"candidate": candidate(), "confirmed": True, "revision": state["revision"]}
    compared = client.post("/api/v1/clothing/compare", json=request)
    assert compared.status_code == 200
    assert compared.json()["matches"][0]["known_suitable"] is False
    assert path.read_bytes() == before
    saved = client.post("/api/v1/clothing/records", json={
        "records": [candidate()], "confirmed": True, "expected_revision": state["revision"],
    })
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["records"]) == 2
    assert openpyxl.load_workbook(path).sheetnames == ["Sheet1"]
    assert set(settings) == {"clothing_workbook_path", "image_model"}


def test_unreviewed_or_invalid_records_cannot_save_or_compare(api):
    client, path, _ = api
    state = client.get("/api/v1/clothing/state").json()
    before = path.read_bytes()
    for confirmed in [False, 1, "true", None]:
        response = client.post("/api/v1/clothing/records", json={"records": [candidate()],
                               "confirmed": confirmed, "expected_revision": state["revision"]})
        assert response.status_code == 422
    for field, value in [("chest_cm", True), ("shoulder_cm", 0), ("length_cm", -1), ("chest_width_cm", 251)]:
        response = client.post("/api/v1/clothing/compare", json={"candidate": {**candidate(), field: value},
                               "confirmed": True, "revision": state["revision"]})
        assert response.status_code == 422
    assert path.read_bytes() == before


def test_stale_revision_and_excel_owner_refuse_mutation(api):
    client, path, _ = api
    state = client.get("/api/v1/clothing/state").json()
    book = openpyxl.load_workbook(path)
    book.active["S2"] = "External edit must survive"
    book.save(path)
    external = path.read_bytes()
    for endpoint, body in [
        ("compare", {"candidate": candidate(), "confirmed": True, "revision": state["revision"]}),
        ("records", {"records": [candidate()], "confirmed": True, "expected_revision": state["revision"]}),
    ]:
        assert client.post(f"/api/v1/clothing/{endpoint}", json=body).status_code == 409
    assert path.read_bytes() == external
    fresh = client.get("/api/v1/clothing/state").json()
    path.with_name("~$" + path.name).touch()
    response = client.post("/api/v1/clothing/records", json={"records": [candidate()], "confirmed": True,
                           "expected_revision": fresh["revision"]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workbook_busy"
    assert path.read_bytes() == external


def test_missing_source_and_bad_configuration_do_not_create_business_files(api, tmp_path):
    client, _, settings = api
    missing = tmp_path / "missing.xlsx"
    response = client.put("/api/v1/clothing/config", json={"workbook_path": str(missing)})
    assert response.status_code == 422 and not missing.exists()
    assert settings["clothing_workbook_path"] != str(missing)
    assert client.put("/api/v1/clothing/config", json={"workbook_path": "relative.xlsx"}).status_code == 422
    settings["clothing_workbook_path"] = str(missing)
    state = client.get("/api/v1/clothing/state").json()
    assert state["error"] and state["revision"] is None


def test_existing_record_identity_cannot_be_overwritten_by_feedback_save(api):
    client, path, _ = api
    state = client.get("/api/v1/clothing/state").json()
    before = path.read_bytes()
    for key, value in [("brand", "Different"), ("component", "内胆"), ("measurement_source", "Invented")]:
        response = client.post("/api/v1/clothing/records", json={"records": [{"row": 2, key: value}],
                               "confirmed": True, "expected_revision": state["revision"]})
        assert response.status_code == 422
        assert path.read_bytes() == before
    updated = client.post("/api/v1/clothing/records", json={"records": [{"row": 2, "mobility_feedback": "未试穿"}],
                          "confirmed": True, "expected_revision": state["revision"]})
    assert updated.status_code == 200
    assert updated.json()["records"][0]["mobility_feedback"] == "未试穿"


def test_confirmed_small_circumference_round_trips_without_reinterpreting_legacy(api):
    client, path, _ = api
    state = client.get("/api/v1/clothing/state").json()
    saved = client.post("/api/v1/clothing/records", json={"records": [{**candidate(), "chest_cm": 64, "size": "XS"}],
                        "confirmed": True, "expected_revision": state["revision"]})
    assert saved.status_code == 200
    read = client.get("/api/v1/clothing/state").json()
    assert read["records"][-1]["chest_cm"] == 64
    assert read["records"][-1]["chest_width_cm"] == 32
    book = openpyxl.load_workbook(path)
    book.active["F2"] = 53
    book.active["I2"] = None
    book.save(path)
    legacy = client.get("/api/v1/clothing/state").json()
    assert legacy["records"][0]["chest_cm"] is None
    update = client.post("/api/v1/clothing/records", json={"records": [{"row": 2, "overall_feedback": "待核对旧口径"}],
                         "confirmed": True, "expected_revision": legacy["revision"]})
    assert update.status_code == 200
    assert client.get("/api/v1/clothing/state").json()["records"][0]["chest_cm"] is None


def image_url():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def test_vision_uses_only_existing_image_config_and_sends_no_history(monkeypatch):
    calls = {}
    config = {"complete": True, "base_url": "https://configured.invalid/v1", "api_key": "test-only-key", "model": "existing-vision"}
    monkeypatch.setattr(clothing_vision, "_vision_provider", lambda: config)

    class FakeClient:
        def __init__(self, **kwargs):
            calls["config"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def create(self, **kwargs):
            calls["request"] = kwargs
            content = '{"records":[{"garment":"Example jacket","component":"外壳","chest_cm":110,"row":2,"overall_feedback":"合适"}]}'
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))])

    monkeypatch.setattr(clothing_vision, "OpenAI", FakeClient)
    result = clothing_vision.extract_clothing(image_url())
    assert result["model"] == "existing-vision"
    record = result["records"][0]
    assert record["row"] is None and record["overall_feedback"] == "" and record["feedback_scope"] == "未知"
    assert calls["config"]["base_url"] == config["base_url"] and calls["config"]["max_retries"] == 0
    assert calls["request"]["model"] == config["model"]
    assert len(calls["request"]["messages"]) == 2
    assert not {"history", "workbook_path", "records"} & calls["request"].keys()


@pytest.mark.parametrize("value", ["https://example.invalid/image.png", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,broken"])
def test_vision_rejects_non_image_or_remote_inputs(value):
    with pytest.raises(clothing_vision.ClothingVisionError):
        clothing_vision._safe_image(value)


def test_invalid_vision_output_and_incomplete_configuration_are_explicit(monkeypatch):
    for content in ["not JSON", '{"records":[]}', '{"records":[{"chest_cm":true}]}', '{"records":[{"component":"other"}]}']:
        with pytest.raises(clothing_vision.ClothingVisionError):
            clothing_vision.parse_extraction(content)
    monkeypatch.setattr(clothing_vision, "_vision_provider", lambda: {"complete": False})
    with pytest.raises(clothing_vision.ClothingVisionError, match="设置"):
        clothing_vision.extract_clothing(image_url())


def test_record_date_validation_is_not_lenient():
    for date in ["2026-02-30", "20260101", "2026-1-1"]:
        with pytest.raises(ValueError):
            ClothingRecord(trial_date=date)


def test_validation_errors_do_not_echo_private_input(api):
    client, _, _ = api
    response = client.post("/api/v1/clothing/extract", json={"image_data_url": {"private": "PRIVATE_SCREENSHOT_MARKER"}})
    assert response.status_code == 422
    assert "PRIVATE_SCREENSHOT_MARKER" not in response.text
    assert response.json()["detail"]["code"] == "clothing_invalid_input"


def test_vision_uses_selected_ai_without_falling_back_or_changing_image_settings(monkeypatch):
    providers = [{"route": "Selected", "model": "selected-vision", "base_url": "https://selected.invalid/v1", "api_key": "test-key"},
                 {"route": "Fallback", "model": "other", "base_url": "https://other.invalid/v1", "api_key": "other-test-key"}]
    monkeypatch.setattr(clothing_vision, "get_provider_chain_config", lambda: providers)
    monkeypatch.setattr(clothing_vision, "load_provider_config", lambda: {"selected_provider": "Selected"})
    assert clothing_vision._vision_provider()["route"] == "Selected"
    assert clothing_vision.vision_status()["provider_route"] == "Selected"
    providers[0]["model"] = "gpt-image-example"
    assert not clothing_vision.vision_status()["ready"]
    with pytest.raises(clothing_vision.ClothingVisionError, match="生成模型"):
        clothing_vision.extract_clothing(image_url())


def test_incomplete_selected_provider_never_sends_to_a_complete_backup(monkeypatch):
    monkeypatch.setattr(clothing_vision, "load_provider_config", lambda: {"selected_provider": "Selected"})
    monkeypatch.setattr(clothing_vision, "get_provider_chain_config", lambda: [
        {"route": "Backup", "model": "other", "base_url": "https://other.invalid/v1", "api_key": "test-only"}])
    monkeypatch.setattr(clothing_vision, "OpenAI", lambda **_kwargs: pytest.fail("Must not transmit to a fallback"))
    assert not clothing_vision.vision_status()["ready"]
    with pytest.raises(clothing_vision.ClothingVisionError, match="不会自动切换"):
        clothing_vision.extract_clothing(image_url())


def test_changed_provider_selection_refuses_transmission(monkeypatch):
    monkeypatch.setattr(clothing_vision, "_vision_provider", lambda: {"route": "Current", "model": "current-model", "complete": True})
    monkeypatch.setattr(clothing_vision, "OpenAI", lambda **_kwargs: pytest.fail("Selection changed; must not transmit"))
    for route, model in [("Old", "current-model"), ("Current", "old-model")]:
        with pytest.raises(clothing_vision.ClothingVisionError, match="选择已变化"):
            clothing_vision.extract_clothing(image_url(), expected_route=route, expected_model=model)
