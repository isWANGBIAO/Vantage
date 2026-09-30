"""Chat context/session persistence and streaming conversation routes."""

import asyncio
import hashlib
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from src.core.config import Config
from src.services.model_call_recorder import (
    get_session_usage_summary,
    get_usage_dashboard_snapshot,
)

from . import action_plans as _action_plans
from . import observability as _observability
from . import processes as _processes

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    provider_route: Optional[str] = None
    context_file: Optional[str] = None
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None
    client_sent_at: Optional[str] = None

_VALID_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

# Level assumed when the client does not choose one. The per-model tiers in the
# provider configuration decide what it actually resolves to.
DEFAULT_CHAT_REASONING_EFFORT = "medium"

_VALID_SERVICE_TIERS = {"priority", "fast"}

def _normalize_reasoning_effort(reasoning_effort: Optional[str]) -> str:
    if reasoning_effort in _VALID_REASONING_EFFORTS:
        return reasoning_effort
    return "medium"

def _normalize_service_tier(service_tier: Optional[str]) -> Optional[str]:
    normalized = str(service_tier or "").strip().lower()
    if normalized in _VALID_SERVICE_TIERS:
        return "priority"
    return None

def _get_history_dir() -> str:
    return str(Config.get_history_dir())

def _get_latest_context_file() -> str:
    return os.path.join(_get_history_dir(), "latest_context.json")

def _resolve_chat_context_file(context_file: Optional[str] = None) -> str:
    default_context = Path(_get_latest_context_file()).resolve()
    if not context_file:
        return str(default_context)

    requested_context = Path(context_file).expanduser().resolve()
    if requested_context != default_context:
        raise ValueError("Unsupported chat context file")
    return str(default_context)

def _get_context_session_file(path: str) -> Path:
    context_path = Path(path)
    return context_path.with_name(f"{context_path.stem}_session.json")

def _read_context_session_payload(path: str):
    session_path = _get_context_session_file(path)
    if not session_path.exists():
        return None

    try:
        with open(session_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None

def _read_context_session_id(path: str):
    payload = _read_context_session_payload(path)
    if not payload:
        return None

    session_id = payload.get("session_id")
    return str(session_id).strip() if session_id else None

def _write_context_session_payload(path: str, payload):
    session_path = _get_context_session_file(path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

def _remove_context_session_payload(path: str):
    session_path = _get_context_session_file(path)
    if session_path.exists():
        session_path.unlink(missing_ok=True)

def _load_context_session_stats(path: str):
    session_id = _read_context_session_id(path)
    if not session_id:
        return None

    try:
        return get_session_usage_summary(
            session_id,
            db_file=Path(_get_history_dir()) / "state.db",
        )
    except Exception as exc:
        logging.warning("Failed to load context session stats for %s: %s", path, exc)
        return None

def _load_context_messages(path: str):
    context_path = Path(path)
    if not context_path.exists():
        return []

    try:
        with open(context_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    return payload if isinstance(payload, list) else []

def _write_context_messages(path: str, messages):
    context_path = Path(path)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    with open(context_path, "w", encoding="utf-8") as handle:
        json.dump(messages, handle, ensure_ascii=False, indent=2)

def _build_chat_display_messages(messages):
    display_messages = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        display_messages.append({
            "role": "assistant",
            "content": content,
        })
    return display_messages

def _build_preferred_chat_model_fields(stats=None):
    latest_payload = _read_context_session_payload(_get_latest_context_file()) or {}
    action_plan_payload = _read_context_session_payload(_action_plans._get_action_plan_context_file()) or {}
    stats_payload = stats if isinstance(stats, dict) else {}

    preferred_model = (
        latest_payload.get("model")
        or action_plan_payload.get("model")
        or stats_payload.get("default_model")
    )
    preferred_provider_route = (
        latest_payload.get("provider_route")
        or action_plan_payload.get("provider_route")
        or stats_payload.get("provider_route")
    )
    preferred_option_id = (
        f"{preferred_provider_route}::{preferred_model}"
        if preferred_model and preferred_provider_route
        else preferred_model
    )
    return {
        "preferred_model": preferred_model,
        "preferred_provider_route": preferred_provider_route,
        "preferred_model_option_id": preferred_option_id,
    }

def _build_chat_context_payload():
    action_plan_context_path = Path(_action_plans._get_action_plan_context_file())
    stats = _load_context_session_stats(_get_latest_context_file())
    preferred_fields = _build_preferred_chat_model_fields(stats)
    if not action_plan_context_path.exists():
        return {
            "base_context_version": "empty",
            "has_action_plan_context": False,
            "display_messages": [],
            "stats": stats,
            **preferred_fields,
        }

    try:
        digest = hashlib.sha1(action_plan_context_path.read_bytes()).hexdigest()
    except OSError:
        digest = "empty"

    action_plan_messages = _load_context_messages(str(action_plan_context_path))
    return {
        "base_context_version": digest or "empty",
        "has_action_plan_context": True,
        "display_messages": _build_chat_display_messages(action_plan_messages),
        "stats": stats,
        **preferred_fields,
    }

@router.get("/api/chat/context")
async def get_chat_context():
    return _build_chat_context_payload()

@router.delete("/api/chat/context")
async def reset_chat_context():
    action_plan_messages = _load_context_messages(_action_plans._get_action_plan_context_file())
    _write_context_messages(_get_latest_context_file(), action_plan_messages)
    action_plan_session_payload = _read_context_session_payload(_action_plans._get_action_plan_context_file())
    if action_plan_session_payload:
        _write_context_session_payload(_get_latest_context_file(), action_plan_session_payload)
    else:
        _remove_context_session_payload(_get_latest_context_file())
    return _build_chat_context_payload()

@router.get("/api/usage")
async def get_usage_dashboard():
    return get_usage_dashboard_snapshot(
        db_file=Path(Config.get_history_dir()) / "state.db",
    )

@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        context_file = _resolve_chat_context_file(request.context_file)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    run_prompt_args = [
        "--chat_message", request.message,
        "--context_file", context_file
    ]
    if request.model:
        run_prompt_args.extend(["--model", request.model])
    if request.provider_route:
        run_prompt_args.extend(["--provider_route", request.provider_route])
    service_tier = _normalize_service_tier(request.service_tier)
    if service_tier:
        run_prompt_args.extend(["--service_tier", service_tier])
    if request.client_sent_at:
        run_prompt_args.extend(["--client_sent_at", request.client_sent_at])
    cmd, run_prompt_cwd = _processes._build_run_prompt_subprocess(run_prompt_args)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["AI_REASONING_EFFORT"] = _normalize_reasoning_effort(request.reasoning_effort)
    if service_tier:
        env["AI_SERVICE_TIER"] = service_tier

    async def process_chat_stream():
        proc = None
        stderr_task = None
        stderr_lines = []
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run_prompt_cwd,
                env=env
            )
            stderr_task = asyncio.create_task(
                _observability._drain_subprocess_stderr(proc.stderr, "chat", stderr_lines)
            )

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = _observability._decode_subprocess_chunk(line)

                msg = decoded.strip()
                if msg:
                    yield json.dumps({"log": msg}) + "\n"

            await proc.wait()
            if stderr_task is not None:
                await stderr_task

            if proc.returncode != 0:
                err_msg = "\n".join(stderr_lines).strip() or f"run_prompt.py exited with code {proc.returncode}"
                logging.error("Chat subprocess failed: %s", err_msg)
                yield json.dumps({"error": err_msg}) + "\n"
        except asyncio.CancelledError:
            logging.warning("Chat stream cancelled by client")
            _processes.terminate_subprocess(proc)
            raise
        finally:
            try:
                if stderr_task is not None and not stderr_task.done():
                    stderr_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await stderr_task
            finally:
                if proc is not None:
                    if proc.returncode is None:
                        logging.warning("Killing orphan chat subprocess")
                    await _processes.reap_subprocess(proc)

    try:
        return StreamingResponse(process_chat_stream(), media_type="application/x-ndjson")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
