"""Chat context/session persistence and streaming conversation routes."""

import asyncio
import hashlib
import json
import logging
import os
import re
import weakref
from contextlib import suppress
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from src.backend.api_contracts import ChatContextResponse, ChatRequest, ChatStreamEvent, ContextErrorResponse
from src.backend.responses import NDJSONResponse, ndjson_openapi
from src.core.config import Config
from src.core.context import (
    ContextReadError, atomic_write_json, context_revision, context_transaction,
    read_context_snapshot, write_context_messages,
)
from src.services.model_call_recorder import (
    get_session_usage_summary,
    get_usage_dashboard_snapshot,
)

from . import action_plans as _action_plans
from . import observability as _observability
from . import processes as _processes

router = APIRouter()

# A turn owns the session until its subprocess is reaped. Distinct event loops
# (including test clients) never reuse an asyncio primitive bound to another loop.
_chat_session_locks = weakref.WeakKeyDictionary()


def _chat_session_lock():
    loop = asyncio.get_running_loop()
    locks = _chat_session_locks.setdefault(loop, {})
    return locks.setdefault(str(Path(_get_latest_context_file()).resolve()), asyncio.Lock())

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
    atomic_write_json(session_path, payload)

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
    return read_context_snapshot(path)[0]


def _unreadable_context_error():
    return HTTPException(status_code=503, detail={
        "code": "CONTEXT_UNREADABLE",
        "message": "Conversation context is unreadable; original files were preserved.",
    })


def _write_context_messages(path: str, messages):
    write_context_messages(path, messages)

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

def _visible_chat_history(messages, action_plan_messages, session):
    """Expose only plan replies and actual chat turns, never model input prompts."""
    base = _build_chat_display_messages(action_plan_messages)
    if action_plan_messages:
        # A mismatched base can occur after a interrupted publication. Do not
        # guess which user-role entries are private analysis prompts.
        if messages[:len(action_plan_messages)] != action_plan_messages:
            return base
        tail = messages[len(action_plan_messages):]
    elif session.get("source") == "chat":
        tail = messages
    else:
        return []
    visible = list(base)
    for message in tail:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if message["role"] == "user":
            content = re.sub(r"^\[Message timestamp: [^\r\n]*\]\n", "", content, count=1)
        visible.append({"role": message["role"], "content": content})
    return visible


def _build_chat_context_payload():
    latest_path = _get_latest_context_file()
    with context_transaction(latest_path):
        action_plan_context_path = Path(_action_plans._get_action_plan_context_file())
        action_plan_messages = _load_context_messages(str(action_plan_context_path))
        latest_messages = _load_context_messages(latest_path)
        session = _read_context_session_payload(latest_path) or {}
        stats = _load_context_session_stats(latest_path)
        try:
            digest = hashlib.sha1(action_plan_context_path.read_bytes()).hexdigest()
        except OSError:
            digest = "empty"
        return {
            "base_context_version": digest,
            "context_version": context_revision(latest_path),
            "has_action_plan_context": action_plan_context_path.exists(),
            "display_messages": _build_chat_display_messages(action_plan_messages),
            "messages": _visible_chat_history(latest_messages, action_plan_messages, session),
            "stats": stats,
            **_build_preferred_chat_model_fields(stats),
        }


@router.get("/api/v1/chat/context", response_model=ChatContextResponse, responses={503: {"model": ContextErrorResponse}})
async def get_chat_context():
    async with _chat_session_lock():
        try:
            return _build_chat_context_payload()
        except ContextReadError:
            raise _unreadable_context_error() from None


@router.delete("/api/v1/chat/context", response_model=ChatContextResponse, responses={503: {"model": ContextErrorResponse}})
async def reset_chat_context():
    async with _chat_session_lock():
        try:
            with context_transaction(_get_latest_context_file()):
                # Validate both files before any destructive reset. A corrupt
                # base/latest file is recoverable data, not an empty session.
                _load_context_messages(_get_latest_context_file())
                action_plan_messages = _load_context_messages(_action_plans._get_action_plan_context_file())
                _write_context_messages(_get_latest_context_file(), action_plan_messages)
                action_plan_session_payload = _read_context_session_payload(_action_plans._get_action_plan_context_file())
                if action_plan_session_payload:
                    _write_context_session_payload(_get_latest_context_file(), action_plan_session_payload)
                else:
                    _remove_context_session_payload(_get_latest_context_file())
                return _build_chat_context_payload()
        except ContextReadError:
            raise _unreadable_context_error() from None

@router.get("/api/v1/usage")
async def get_usage_dashboard():
    return get_usage_dashboard_snapshot(
        db_file=Path(Config.get_history_dir()) / "state.db",
    )

@router.post("/api/v1/chat", response_class=NDJSONResponse,
             responses={200: {"model": ChatStreamEvent, "description": "UTF-8 NDJSON; one chat event per line."}},
             openapi_extra=ndjson_openapi(ChatStreamEvent))
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

    async def serialized_chat_stream():
        async with _chat_session_lock():
            iterator = process_chat_stream()
            try:
                async for event in iterator:
                    yield event
            finally:
                await iterator.aclose()

    try:
        return StreamingResponse(serialized_chat_stream(), media_type="application/x-ndjson")
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
