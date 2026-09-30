import asyncio
import sys
from types import SimpleNamespace

from src.backend import face, processes
from src.core.backend_runtime_packaging import PYINSTALLER_HIDDEN_IMPORTS
from src.scripts import run_server_background as launcher
from src.scripts import verify_backend_runtime as verifier


def test_frozen_face_analysis_and_export_dispatch_packaged_modes(monkeypatch, tmp_path):
    monkeypatch.setattr(processes.sys, "frozen", True, raising=False)
    monkeypatch.setattr(processes, "_get_runtime_workdir", lambda: tmp_path)
    command, cwd = processes._build_face_analysis_subprocess(["--export"])
    assert command == [sys.executable, "--run-face-analysis", "--export"]
    assert cwd == str(tmp_path)
    assert "src.scripts.analyze_face" in PYINSTALLER_HIDDEN_IMPORTS


def test_face_bridge_preserves_arguments_without_starting_server(monkeypatch):
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)
    original = sys.argv[:]
    captured = []
    launcher._run_face_analysis_entrypoint(["--export"], analysis_main=lambda: captured.extend(sys.argv))
    assert captured == ["analyze_face.py", "--export"]
    assert sys.argv == original


def test_launcher_routes_face_mode_before_server_start(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["VantageBackend", "--run-face-analysis", "--export"])
    captured = []
    monkeypatch.setattr(launcher, "_run_face_analysis_entrypoint", lambda args: captured.extend(args))
    monkeypatch.setattr(launcher, "_main_without_backend_runtime_lock", lambda: (_ for _ in ()).throw(AssertionError("must not start server")))
    launcher.main()
    assert captured == ["--export"]


def test_export_endpoint_uses_the_frozen_dispatcher(monkeypatch, tmp_path):
    monkeypatch.setattr(processes.sys, "frozen", True, raising=False)
    monkeypatch.setattr(processes, "_get_runtime_workdir", lambda: tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"No cached rows", stderr=b"")

    monkeypatch.setattr(face.subprocess, "run", run)
    response = asyncio.run(face.export_face_excel())
    assert response.status_code == 500
    assert calls[0][0] == [sys.executable, "--run-face-analysis", "--export"]
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_new_face_job_cannot_expose_an_old_done_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(face, "_get_face_analysis_db_file", lambda: tmp_path / "face.db")
    monkeypatch.setattr(face, "_face_analysis_job_running", True)
    monkeypatch.setattr(face, "_face_analysis_job_started_at", 200)
    monkeypatch.setattr(face, "_face_analysis_job_error", None)
    monkeypatch.setattr(face, "initialize_face_analysis_storage", lambda *_args: None)
    monkeypatch.setattr(face, "load_face_progress_cache", lambda *_args: {"status": "done", "percent": 100, "timestamp": 100})
    result = asyncio.run(face.get_face_progress())
    assert result["status"] == "queued"
    assert result["percent"] == 0


def test_face_process_error_remains_visible(monkeypatch, tmp_path):
    monkeypatch.setattr(face, "_get_face_analysis_db_file", lambda: tmp_path / "face.db")
    monkeypatch.setattr(face, "_face_analysis_job_running", False)
    monkeypatch.setattr(face, "_face_analysis_job_error", "Face analysis failed. See System Logs for details.")
    monkeypatch.setattr(face, "initialize_face_analysis_storage", lambda *_args: None)
    monkeypatch.setattr(face, "load_face_progress_cache", lambda *_args: None)
    result = asyncio.run(face.get_face_progress())
    assert result["status"] == "error"
    assert "failed" in result["error"]


def test_cached_face_export_does_not_need_mounted_photo_volume(monkeypatch, tmp_path, capsys):
    from src.scripts import analyze_face
    monkeypatch.setattr(sys, "argv", ["analyze_face.py", "--export"])
    monkeypatch.setattr(analyze_face, "get_default_db_file", lambda: tmp_path / "face.db")
    monkeypatch.setattr(analyze_face, "get_default_plot_output_dir", lambda: tmp_path / "plots")
    monkeypatch.setattr(analyze_face, "export_excel", lambda *_args: str(tmp_path / "face.xlsx"))
    monkeypatch.setattr(analyze_face, "discover_photo_search_paths", lambda: (_ for _ in ()).throw(AssertionError("cached export must not scan photos")))
    analyze_face.main()
    assert "EXPORT_PATH:" in capsys.readouterr().out


def test_packaged_face_entrypoint_smoke_uses_help_without_analyzing(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="usage: VantageBackend --export", stderr="")

    monkeypatch.setattr(verifier.subprocess, "run", run)
    verifier._run_packaged_face_entrypoint_smoke(tmp_path / "VantageBackend", cwd=tmp_path, env={})
    assert calls == [[str(tmp_path / "VantageBackend"), "--run-face-analysis", "--help"]]
