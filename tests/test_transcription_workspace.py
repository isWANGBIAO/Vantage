"""Request ownership covers uploads and child-created derivatives, even on kill."""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

from src.backend import transcription


VOICE = {"complete": True, "base_url": "http://127.0.0.1/synthetic", "api_key": "synthetic",
         "model": "synthetic", "mode": "custom", "route": None, "missing": []}


@pytest.mark.parametrize("mode", ["timeout", "cancel", "success", "failure"])
def test_request_cleans_all_derivatives_after_child_finishes(monkeypatch, tmp_path, mode):
    monkeypatch.setattr(transcription.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(transcription, "_load_voice_transcription_config", lambda: VOICE)
    monkeypatch.setattr(transcription, "TRANSCRIBE_TIMEOUT_SECONDS", 2 if mode == "timeout" else 5)
    child = """
import pathlib,sys,time
source=pathlib.Path(sys.argv[1])
source.with_name(source.stem + '_converted.wav').write_bytes(b'synthetic converted audio')
mode=sys.argv[2]
if mode in ('timeout','cancel'): time.sleep(30)
if mode=='failure': print('TRANSCRIPTION_ERROR:synthetic failure',flush=True); sys.exit(1)
print('TRANSCRIPTION_RESULT:synthetic transcript',flush=True)
"""
    monkeypatch.setattr(transcription._processes, "_build_run_prompt_subprocess", lambda args: (
        [sys.executable, "-c", child, args[args.index("--transcribe") + 1], mode], str(tmp_path)))
    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(transcription.asyncio, "create_subprocess_exec", spawn)

    async def read():
        return b"synthetic upload"

    async def exercise():
        task = asyncio.create_task(transcription.transcribe_audio(SimpleNamespace(filename="recording.webm", read=read)))
        if mode == "cancel":
            async def wait_converted():
                while not list(tmp_path.rglob("*_converted.wav")):
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(wait_converted(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            if mode == "success":
                assert result["transcription"] == "synthetic transcript"
            else:
                assert result.status_code == (504 if mode == "timeout" else 500)
                assert "error" in json.loads(result.body)
        assert children and all(child.returncode is not None for child in children)

    asyncio.run(exercise())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error_type", [OSError, asyncio.CancelledError])
def test_upload_read_failure_or_cancel_cleans_the_request_workspace(monkeypatch, tmp_path, error_type):
    monkeypatch.setattr(transcription.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(transcription, "_load_voice_transcription_config", lambda: VOICE)

    async def read():
        raise error_type("synthetic upload interrupted")

    with pytest.raises(error_type):
        asyncio.run(transcription.transcribe_audio(SimpleNamespace(filename="recording.webm", read=read)))
    assert list(tmp_path.iterdir()) == []


def test_reaping_transcription_terminates_its_file_holding_descendant(tmp_path):
    import psutil
    from src.backend.processes import reap_subprocess

    pid_file = tmp_path / "descendant.pid"
    held_file = tmp_path / "converted.wav"
    child = "import pathlib,sys,time; f=open(sys.argv[1],'wb'); f.write(b'synthetic'); f.flush(); time.sleep(30)"
    parent = ("import pathlib,subprocess,sys,time; "
              f"p=subprocess.Popen([sys.executable,'-c',{child!r},{str(held_file)!r}]); "
              f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)")

    async def exercise():
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", parent,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            async def wait_child():
                while not pid_file.exists() or not held_file.exists():
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(wait_child(), 5)
            descendant = psutil.Process(int(pid_file.read_text()))
            await asyncio.wait_for(reap_subprocess(process, terminate_descendants=True), 5)
            assert not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE
            assert process.returncode is not None
            os.remove(held_file)  # Windows would refuse this while the child held it open.
        finally:
            if process.returncode is None:
                await reap_subprocess(process, terminate_descendants=True)

    asyncio.run(exercise())


def test_eight_same_name_uploads_have_isolated_workspace_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(transcription.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(transcription, "_load_voice_transcription_config", lambda: VOICE)
    child = ("import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
             "p.with_name(p.stem+'_converted.wav').write_bytes(b'synthetic'); "
             "print('TRANSCRIPTION_RESULT:complete',flush=True)")
    paths = []

    def build(args):
        upload = args[args.index("--transcribe") + 1]
        paths.append(upload)
        return [sys.executable, "-c", child, upload], str(tmp_path)

    monkeypatch.setattr(transcription._processes, "_build_run_prompt_subprocess", build)

    async def read():
        return b"synthetic upload"

    async def exercise():
        results = await asyncio.gather(*(transcription.transcribe_audio(
            SimpleNamespace(filename="recording.webm", read=read)) for _ in range(8)))
        assert all(result["transcription"] == "complete" for result in results)

    asyncio.run(exercise())
    from pathlib import Path
    assert len({Path(path).parent for path in paths}) == 8
    assert list(tmp_path.iterdir()) == []


def test_real_ffmpeg_webm_conversion_is_cleaned_after_provider_timeout(monkeypatch, tmp_path):
    import shutil
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("Optional FFmpeg executable is not installed")
    source = tmp_path / "synthetic.webm"
    created = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                              "-t", "0.1", "-c:a", "libopus", str(source)], capture_output=True, timeout=15)
    if created.returncode:
        pytest.skip("Installed FFmpeg does not support the synthetic WebM fixture")
    reached = threading.Event()
    release = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            reached.set()
            release.wait(10)
            try:
                self.send_response(200)
                self.send_header("Content-Length", "16")
                self.end_headers()
                self.wfile.write(b'{"text":"ready"}')
            except OSError:
                pass

        def log_message(self, *args):
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(transcription.tempfile, "tempdir", str(uploads))
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VANTAGE_HISTORY_DIR", str(tmp_path / "state" / "history"))
    monkeypatch.setattr(transcription, "_load_voice_transcription_config", lambda: {
        **VOICE, "base_url": f"http://127.0.0.1:{provider.server_port}/v1"})
    monkeypatch.setattr(transcription, "TRANSCRIBE_TIMEOUT_SECONDS", 4)

    async def read():
        return source.read_bytes()

    try:
        result = asyncio.run(transcription.transcribe_audio(SimpleNamespace(filename="recording.webm", read=read)))
        assert reached.is_set(), "The real conversion must reach the synthetic provider before timing out"
        assert result.status_code == 504
        assert list(uploads.iterdir()) == []
    finally:
        release.set()
        provider.shutdown()
        provider.server_close()
        thread.join(5)
