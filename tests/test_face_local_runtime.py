import sys
from pathlib import Path

import pytest

from src.services import face_local_runtime as local


def settings(tmp_path, method="onnx"):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"fixture")
    sam = tmp_path / "sam"
    sam.mkdir(exist_ok=True)
    (sam / "config.json").write_text("{}")
    return {"face_analysis_method": method, "face_analysis_python": sys.executable,
            "face_analysis_onnx_model": str(model), "face_analysis_sam3_model_dir": str(sam)}


def test_empty_environment_never_uses_packaged_python(tmp_path):
    status = local.configuration_status({}, history_root=tmp_path)
    assert status["ready"] is False
    assert "Python" in status["message"]


def test_profiles_isolate_methods_and_model_changes(tmp_path):
    values = settings(tmp_path)
    first = local.profile_paths(values, history_root=tmp_path)
    values["face_analysis_method"] = "sam3"
    second = local.profile_paths(values, history_root=tmp_path)
    assert first["db_file"] != second["db_file"]
    assert first["db_file"].parent.is_relative_to(tmp_path)
    assert tmp_path / "face_analysis.db" not in (first["db_file"], second["db_file"])
    values["face_analysis_method"] = "onnx"
    Path(values["face_analysis_onnx_model"]).write_bytes(b"changed model")
    assert local.profile_paths(values, history_root=tmp_path)["profile_id"] != first["profile_id"]


def test_worker_command_uses_selected_interpreter_and_local_source(tmp_path):
    values = settings(tmp_path)
    command = local.build_worker_command(values)
    assert command[0] == sys.executable
    assert command[1] == "-u"
    assert command[2].endswith("face_model_worker.py")
    assert "pip" not in command


def test_missing_model_reports_unavailable(tmp_path):
    values = settings(tmp_path)
    Path(values["face_analysis_onnx_model"]).unlink()
    assert local.configuration_status(values, history_root=tmp_path)["ready"] is False


def test_bad_worker_response_stops_worker():
    assert local.decode_worker_response('{"ok":false,"error":"MissingDependency: onnxruntime"}') == {
        "ok": False, "error": "MissingDependency: onnxruntime"}
    with pytest.raises(local.LocalModelError):
        local.decode_worker_response("not-json")
    with pytest.raises(local.LocalModelError):
        local.decode_worker_response('{"ok":true}')


def test_optional_packages_stay_outside_main_process():
    import inspect
    source = inspect.getsource(local)
    assert "import onnxruntime" not in source
    assert "import torch" not in source
    assert "from transformers" not in source


def test_sam3_can_use_existing_separate_python(tmp_path):
    values = settings(tmp_path, "sam3")
    values["face_analysis_sam3_python"] = str(tmp_path / "sam3-python.exe")
    Path(values["face_analysis_sam3_python"]).write_bytes(b"local env")
    assert local.build_worker_command(values)[0] == values["face_analysis_sam3_python"]
    assert local.configuration_status(values, history_root=tmp_path)["ready"] is True


def test_timeout_reaps_worker_and_does_not_return_a_score(tmp_path):
    import io
    import queue
    import numpy as np
    class Child:
        def __init__(self):
            self.stdin, self.stdout = io.StringIO(), io.StringIO()
            self.terminated = False
        def poll(self):
            return 0 if self.terminated else None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout):
            return 0
    runtime = local.LocalFaceRuntime(settings(tmp_path), timeout=.01)
    child = runtime.process = Child()
    runtime.responses = queue.Queue()
    with pytest.raises(local.LocalModelError, match="超时"):
        runtime.request(np.zeros((512, 512, 3), dtype=np.uint8))
    assert child.terminated
    assert runtime.process is None
    assert runtime.last_error


def test_send_timeout_is_bounded_even_if_child_never_reads(tmp_path):
    import io
    import queue
    import threading
    import numpy as np
    released, done = threading.Event(), threading.Event()
    class Stdin:
        def write(self, data):
            released.wait()
        def flush(self):
            pass
        def close(self):
            pass
    class Child:
        stdin, stdout = Stdin(), io.StringIO()
        def poll(self):
            return None
        def terminate(self):
            released.set()
        def wait(self, timeout):
            return 0
    runtime = local.LocalFaceRuntime(settings(tmp_path), timeout=.05)
    runtime.process, runtime.responses = Child(), queue.Queue()
    errors = []
    def run():
        try:
            runtime.request(np.random.default_rng(1).integers(0, 255, (512, 512, 3), dtype=np.uint8))
        except local.LocalModelError as exc:
            errors.append(exc)
        finally:
            done.set()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    completed = done.wait(.5)
    released.set()
    thread.join(1)
    assert completed, "send phase must be covered by the timeout"
    assert errors


def test_backfill_does_not_replace_newer_overlay(tmp_path, monkeypatch):
    import base64
    from datetime import datetime
    import numpy as np
    from src.services.face_analysis_pipeline import AnalysisConfig
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    runtime = local.LocalFaceRuntime(settings(tmp_path))
    class Detector:
        def detect(self, image):
            return (160, 130, 200, 240)
    responses = iter([{"passed": True, "score": 20, "_overlay": base64.b64encode(b"new").decode()},
                      {"passed": True, "score": 10, "_overlay": base64.b64encode(b"old").decode()}])
    monkeypatch.setattr(runtime, "request", lambda image: next(responses))
    image = np.random.default_rng(1).integers(50, 200, (512, 512, 3), dtype=np.uint8)
    runtime.analyze(image, detector=Detector(), source_path="new.jpg", observed_at=datetime(2026, 10, 13))
    runtime.analyze(image, detector=Detector(), source_path="old.jpg", observed_at=datetime(2026, 10, 12))
    assert runtime.paths["overlay"].read_bytes() == b"new"
