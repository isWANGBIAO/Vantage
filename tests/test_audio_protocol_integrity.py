import asyncio
import sys
from types import SimpleNamespace

import pytest

from src.backend import transcription
from src.services.audio_service import AudioService


@pytest.mark.parametrize("extension,expected", [("MP3", "audio/mpeg"), ("FLAC", "audio/flac"),
                                                ("M4A", "audio/mp4"), ("WAV", "audio/wav"),
                                                ("WEBM", "audio/webm")])
def test_uppercase_audio_extensions_keep_the_correct_mime(monkeypatch, tmp_path, extension, expected):
    path = tmp_path / f"synthetic.{extension}"
    path.write_bytes(b"synthetic audio")
    monkeypatch.setattr(AudioService, "convert_to_wav", lambda *_: None)
    captured = []

    def post(*args, **kwargs):
        captured.append(kwargs["files"]["file"][2])
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {"text": "synthetic"})

    monkeypatch.setattr("src.services.audio_service.requests.post", post)
    assert AudioService.transcribe(str(path), base_url="http://127.0.0.1/synthetic",
                                   api_key="synthetic", model="synthetic") == "synthetic"
    assert captured == [expected]


def test_multiline_transcription_survives_real_run_prompt_child(monkeypatch, tmp_path):
    text = "first line\n第二行🙂\nthird line"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VANTAGE_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(transcription, "_load_voice_transcription_config", lambda: {
        "complete": True, "base_url": "http://127.0.0.1/synthetic", "api_key": "synthetic",
        "model": "synthetic", "mode": "custom", "route": None, "missing": [],
    })
    child = ("from src.scripts import run_prompt; "
             f"run_prompt.AudioService.transcribe=lambda *args,**kwargs: {text!r}; "
             "run_prompt.main()")
    from pathlib import Path
    root = Path(transcription.__file__).resolve().parents[2]
    monkeypatch.setattr(transcription._processes, "_build_run_prompt_subprocess", lambda args: (
        [sys.executable, "-c", child, *args], str(root)))

    async def read():
        return b"synthetic upload"

    result = asyncio.run(transcription.transcribe_audio(SimpleNamespace(filename="test.wav", read=read)))
    assert result["transcription"] == text
