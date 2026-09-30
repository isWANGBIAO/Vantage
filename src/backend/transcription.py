"""Audio transcription subprocess lifecycle and HTTP adapter."""

import asyncio
import os
import tempfile
from contextlib import suppress

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from . import processes as _processes
from . import providers as _providers

router = APIRouter()

TRANSCRIBE_TIMEOUT_SECONDS = 60

def _load_voice_transcription_config():
    return _providers._resolve_special_provider_config(kind="voice")

@router.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    voice_config = _load_voice_transcription_config()
    if not voice_config["complete"]:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Voice transcription provider is not configured",
                "details": "Configure voice Base URL, API key, and model in Settings.",
                "voice_model": voice_config["model"],
                "voice_base_url": voice_config["base_url"],
                "voice_provider_mode": voice_config.get("mode"),
                "voice_provider_route": voice_config.get("route"),
                "configuration_error": True,
                "missing": voice_config["missing"],
            },
        )

    original_filename = file.filename or "recording.webm"
    ext = os.path.splitext(original_filename)[1] or ".webm"

    temp_fd, temp_filename = tempfile.mkstemp(prefix="temp_audio_", suffix=ext)

    print(f"[Transcribe] Saving uploaded file to: {temp_filename}")

    with os.fdopen(temp_fd, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        print(f"[Transcribe] File size: {len(content)} bytes")

    cmd, run_prompt_cwd = _processes._build_run_prompt_subprocess([
        "--transcribe",
        temp_filename,
        "--transcribe-base-url",
        voice_config["base_url"],
        "--transcribe-model",
        voice_config["model"],
    ])
    print(f"[Transcribe] Running command: {_providers._redact_subprocess_command_for_log(cmd, api_key=voice_config['api_key'])}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VANTAGE_TRANSCRIBE_API_KEY"] = voice_config["api_key"]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=run_prompt_cwd,
            env=env
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=TRANSCRIBE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            if proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass
                with suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5)
            return JSONResponse(
                status_code=504,
                content={
                    "error": "Transcription timed out",
                    "details": f"Voice transcription exceeded {TRANSCRIBE_TIMEOUT_SECONDS} seconds.",
                    "voice_model": voice_config["model"],
                    "voice_base_url": voice_config["base_url"],
                    "voice_provider_mode": voice_config.get("mode"),
                    "voice_provider_route": voice_config.get("route"),
                    "configuration_error": False,
                },
            )

        output = ""
        try:
            output = stdout.decode('utf-8')
        except UnicodeDecodeError:
            output = stdout.decode('gbk', errors='replace')

        if stderr:
            try:
                stderr_text = stderr.decode('utf-8')
            except UnicodeDecodeError:
                stderr_text = stderr.decode('gbk', errors='replace')
            stderr_text = _providers._redact_api_key_from_message(stderr_text, voice_config["api_key"])
            print(f"[Transcribe] Stderr: {stderr_text}")
        else:
            stderr_text = ""

        print(f"[Transcribe] Stdout received: {len(output)} chars")

        transcription = ""
        transcription_error = ""
        for line in output.splitlines():
            if line.startswith("TRANSCRIPTION_RESULT:"):
                transcription = line.replace("TRANSCRIPTION_RESULT:", "").strip()
                break
            if line.startswith("TRANSCRIPTION_ERROR:"):
                transcription_error = line.replace("TRANSCRIPTION_ERROR:", "").strip()

        if proc.returncode != 0:
            details = _providers._redact_api_key_from_message(
                transcription_error or stderr_text or output.strip(),
                voice_config["api_key"],
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Transcription failed",
                    "details": details,
                    "voice_model": voice_config["model"],
                    "voice_base_url": voice_config["base_url"],
                    "voice_provider_mode": voice_config.get("mode"),
                    "voice_provider_route": voice_config.get("route"),
                    "configuration_error": False,
                },
            )

        if not transcription:
            details = _providers._redact_api_key_from_message(
                transcription_error or stderr_text or output.strip() or "No transcription result returned",
                voice_config["api_key"],
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Transcription failed",
                    "details": details,
                    "voice_model": voice_config["model"],
                    "voice_base_url": voice_config["base_url"],
                    "configuration_error": False,
                },
            )

        print(f"[Transcribe] Result length: {len(transcription)} chars")

        return {
            "transcription": transcription,
            "voice_model": voice_config["model"],
            "voice_base_url": voice_config["base_url"],
            "voice_provider_mode": voice_config.get("mode"),
            "voice_provider_route": voice_config.get("route"),
        }
    finally:
        try:
            if proc is not None and proc.returncode is None:
                with suppress(Exception):
                    await asyncio.wait_for(_processes.reap_subprocess(proc), timeout=5)
        finally:
            if os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except OSError as exc:
                    print(f"[Transcribe] Failed to remove temp file {temp_filename}: {exc}")
