import json

import pytest
from fastapi import HTTPException

from src.backend import settings
from src.core import user_config
from src.services.automation_catalog import get_operation


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    monkeypatch.setattr(user_config.Config, "get_config_dir", staticmethod(lambda: tmp_path / "config"))
    monkeypatch.setattr(user_config.Config, "get_project_root", staticmethod(lambda: tmp_path / "project"))
    return tmp_path


def test_face_local_settings_have_portable_empty_defaults(local_config):
    loaded = user_config.load_settings()
    assert loaded["face_analysis_method"] == "onnx"
    for field in ("face_analysis_python", "face_analysis_sam3_python", "face_analysis_onnx_model", "face_analysis_sam3_model_dir"):
        assert loaded[field] == ""


def test_face_local_settings_persist_via_shared_api(local_config):
    python = local_config / "python.exe"
    python.touch()
    model = local_config / "model.onnx"
    model.touch()
    sam3 = local_config / "sam3"
    sam3.mkdir()
    payload = {
        "face_analysis_method": "sam3",
        "face_analysis_python": str(python),
        "face_analysis_sam3_python": str(python),
        "face_analysis_onnx_model": str(model),
        "face_analysis_sam3_model_dir": str(sam3),
    }
    settings.update_automation_settings(payload)
    loaded = user_config.load_settings()
    assert {key: loaded[key] for key in payload} == payload
    persisted = json.loads(user_config.get_settings_file().read_text(encoding="utf-8"))
    assert {key: persisted[key] for key in payload} == payload
    settings.update_automation_settings({key: "" for key in payload if key != "face_analysis_method"})
    assert user_config.load_settings()["face_analysis_python"] == ""


@pytest.mark.parametrize("payload", [
    {"face_analysis_method": "auto"},
    {"face_analysis_method": None},
    {"face_analysis_python": False},
    {"face_analysis_sam3_python": False},
    {"face_analysis_onnx_model": []},
    {"face_analysis_sam3_model_dir": 12},
    {"face_analysis_python": "missing-python.exe"},
])
def test_face_local_settings_reject_invalid_payload_without_writes(local_config, payload):
    with pytest.raises(HTTPException) as failure:
        settings.update_automation_settings(payload)
    assert failure.value.status_code == 422
    assert not user_config.get_settings_file().exists()


def test_catalog_exposes_face_settings(local_config):
    properties = get_operation("settings.update").input_schema["properties"]
    assert properties["face_analysis_method"]["enum"] == ["onnx", "sam3"]
    for field in ("face_analysis_python", "face_analysis_sam3_python", "face_analysis_onnx_model", "face_analysis_sam3_model_dir"):
        assert properties[field]["type"] == "string"


def test_catalog_exposes_read_only_local_face_status():
    operation = get_operation("face.local_status.read")
    assert (operation.method, operation.path) == ("GET", "/api/v1/face/local-status")
    assert not operation.mutation
    assert not operation.side_effect
