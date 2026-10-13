import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.backend import face
from src.services.face_analysis_pipeline import analyze_image_data
from src.services.face_local_runtime import profile_paths
from src.core.backend_runtime_packaging import REQUIRED_RESOURCE_SPECS, PYINSTALLER_EXCLUDES


def test_pipeline_dispatches_strict_external_analysis_without_fallback():
    class Parser:
        is_external_local = True
        def analyze(self, image, **kwargs):
            return {"passed": False, "fail_reason": ["brows_missing"], "score": None}
    import numpy as np
    result = analyze_image_data(np.zeros((12, 12, 3), dtype=np.uint8), None, Parser())
    assert result["fail_reason"] == ["brows_missing"]


def test_local_status_does_not_start_model(tmp_path):
    with patch.dict("os.environ", {"VANTAGE_DATA_DIR": str(tmp_path)}):
        result = asyncio.run(face.get_face_local_status())
    assert result["method"] == "onnx"
    assert result["ready"] is False


def test_overlay_cannot_request_other_profile(tmp_path):
    with patch.dict("os.environ", {"VANTAGE_DATA_DIR": str(tmp_path)}):
        with pytest.raises(HTTPException) as error:
            asyncio.run(face.get_face_overlay(profile_id="../../private"))
    assert error.value.status_code == 404


def test_profile_database_preserves_legacy_file(tmp_path):
    legacy = tmp_path / "face_analysis.db"
    legacy.write_bytes(b"private old history")
    with patch.object(face.Config, "get_history_dir", return_value=tmp_path), patch.object(face, "FACE_ANALYSIS_DB_FILE", None):
        current = face._get_face_analysis_db_file()
    assert current != legacy
    assert legacy.read_bytes() == b"private old history"


def test_packaging_bundles_only_worker_support_code_not_optional_models():
    sources = {source for source, _ in REQUIRED_RESOURCE_SPECS}
    assert "src/scripts/face_model_worker.py" in sources
    assert "src/services/face_brow_analysis.py" in sources
    assert "onnxruntime" in PYINSTALLER_EXCLUDES
    assert "torch" in PYINSTALLER_EXCLUDES
    assert not any("parsing_resnet18.onnx" in source or "sam3/model" in source for source in sources)
