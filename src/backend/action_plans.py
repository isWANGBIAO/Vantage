"""Action-plan sources, saved results, and generation stream orchestration."""

from pydantic import BaseModel
from src.utils.data_loader import DataLoader
from fastapi.responses import JSONResponse
from typing import Optional
from pathlib import Path
from fastapi.responses import StreamingResponse
import asyncio
from datetime import datetime
import glob
import hashlib
import json
import logging
import os
import subprocess
from contextlib import suppress
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/action_plan/today")
async def get_today_action_plan():
    """Return today's latest action plan if it exists"""
    today = datetime.now().strftime("%Y%m%d")

    try:
        latest_file = _get_latest_action_plan_file(today)
        if latest_file is None:
            return {
                "exists": False,
                "analysis": None,
                "plan": None,
                "meta": None,
                "date": today,
            }

        payload = _load_action_plan_payload(latest_file)
        if not payload:
            return {
                "exists": False,
                "analysis": None,
                "plan": None,
                "meta": None,
                "date": today,
                "error": f"Invalid action plan payload: {os.path.basename(latest_file)}",
            }
        payload = _hydrate_action_plan_input(payload)

        return {
            "exists": True,
            "analysis": payload.get("analysis"),
            "plan": payload.get("plan"),
            "meta": payload.get("meta"),
            "date": payload.get("date") or today,
            "filename": os.path.basename(latest_file),
            "id": payload.get("id"),
        }
    except Exception as e:
        return {
            "exists": False,
            "analysis": None,
            "plan": None,
            "meta": None,
            "error": str(e),
            "date": today,
        }

def _get_action_plan_context_file() -> str:
    return os.path.join(_chat._get_history_dir(), "latest_action_plan_context.json")

def _load_action_plan_payload(path: str):
    action_plan_path = Path(path)
    if not action_plan_path.exists():
        return None

    try:
        with open(action_plan_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    return payload if isinstance(payload, dict) else None

def _hydrate_action_plan_input(payload):
    if not isinstance(payload, dict):
        return payload

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return payload

    existing_input = meta.get("input")
    if isinstance(existing_input, dict) and any(existing_input.values()):
        return payload

    messages = _chat._load_context_messages(_get_action_plan_context_file())
    if len(messages) < 5:
        return payload

    expected_roles = ["system", "user", "assistant", "user", "assistant"]
    if [message.get("role") for message in messages[:5]] != expected_roles:
        return payload

    analysis_body = (payload.get("analysis") or {}).get("body") or ""
    plan_body = (payload.get("plan") or {}).get("body") or ""
    if messages[2].get("content") != analysis_body or messages[4].get("content") != plan_body:
        return payload

    meta["input"] = {
        "system_prompt": messages[0].get("content") or "",
        "analysis_prompt": messages[1].get("content") or "",
        "plan_prompt": messages[3].get("content") or "",
    }
    return payload

def _get_latest_action_plan_file(target_date: Optional[str] = None):
    files = _list_today_action_plan_files(target_date)
    if not files:
        return None
    return max(files, key=os.path.getmtime)

def _list_today_action_plan_files(target_date: Optional[str] = None):
    today = target_date or datetime.now().strftime("%Y%m%d")
    pattern = os.path.join(_chat._get_history_dir(), f"action_plan_{today}_*.json")
    return glob.glob(pattern)

def _replace_today_action_plan_files(previous_files):
    current_files = _list_today_action_plan_files()
    if not current_files:
        return None

    keep_file = max(current_files, key=os.path.getmtime)
    previous_file_paths = {os.path.abspath(path) for path in previous_files}
    current_file_paths = {os.path.abspath(path) for path in current_files}
    created_files = current_file_paths - previous_file_paths

    if previous_file_paths and not created_files and os.path.abspath(keep_file) in previous_file_paths:
        return keep_file

    for path in current_files:
        if os.path.abspath(path) == os.path.abspath(keep_file):
            continue
        try:
            os.remove(path)
        except OSError as exc:
            print(f"Failed to remove replaced action plan file {path}: {exc}")

    return keep_file

class ActionPlanRequest(BaseModel):
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = None
    model: Optional[str] = None
    provider_route: Optional[str] = None
    replace_today: bool = False
    wait_for_provider_ready: bool = False

ACTION_PLAN_REQUIRED_DATA_FILES = ("Time.xlsx",)

# Everything the Action Plan reads besides the required workbook. The content
# fingerprint has to cover all of it: an edit to the balance sheet or to any of
# the prompts changes the generated plan, so it must be able to trigger a
# refresh. These are read if present but are never treated as missing inputs.
ACTION_PLAN_CONTENT_FILES = (
    "Balance Sheet.xlsx",
    "Prompt_Personal_Info.md",
    "Prompt_Action_Plan.md",
    "Prompt_Project_Management.md",
    "Prompt_Advisor_Requirements.md",
    "Prompt_Goals.md",
    "Prompt_Inventory.md",
    "Prompt_AI_Instructions.md",
    "Prompt_Scientific_Theory.md",
)

# Workbook sources can be held open by Excel, so they are hashed through the
# same locked-file snapshot path as the rest of the app. The other sources are
# plain text and are read directly.
_ACTION_PLAN_WORKBOOK_FILES = ("Time.xlsx", "Balance Sheet.xlsx")

def _hash_action_plan_source(path: Path, name: str, digest) -> None:
    """Feed one source file into the fingerprint, guarding against mid-read edits."""
    is_workbook = path.suffix.lower() == ".xlsx"
    before = path.stat()
    digest.update(name.encode("utf-8"))
    digest.update(b"\0")
    if is_workbook:
        snapshot = DataLoader._safe_copy_excel(path)
        try:
            with snapshot.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        finally:
            snapshot.unlink(missing_ok=True)
    else:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size, after.st_mtime_ns, after.st_ino
    ):
        raise OSError("Action plan source changed while reading")

def _resolve_action_plan_content_source(filename: str):
    """Resolve one optional source, or None when it is absent."""
    try:
        return Path(DataLoader.resolve_data_path(filename))
    except FileNotFoundError:
        return None

def _compute_action_plan_source_revision():
    """Hash source bytes, rejecting a file that changes while it is read."""
    digest = hashlib.sha256()
    for filename in ACTION_PLAN_REQUIRED_DATA_FILES:
        path = Path(DataLoader.resolve_data_path(filename))
        _hash_action_plan_source(path, filename, digest)
    for filename in ACTION_PLAN_CONTENT_FILES:
        path = _resolve_action_plan_content_source(filename)
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        if path is None or not path.exists():
            # Record the absence so creating the file later also moves the fingerprint.
            digest.update(b"<missing>")
            continue
        _hash_action_plan_source(path, filename, digest)
    return digest.hexdigest()

@router.get("/api/action_plan/source_revision")
async def get_action_plan_source_revision():
    try:
        revision = await asyncio.to_thread(_compute_action_plan_source_revision)
    except (OSError, subprocess.CalledProcessError):
        return JSONResponse(
            status_code=503,
            content={"error": "行动计划数据源暂不可用，请稍后重试。"},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(content={"revision": revision}, headers={"Cache-Control": "no-store"})

def _get_missing_action_plan_data_sources():
    missing_sources = []
    for filename in ACTION_PLAN_REQUIRED_DATA_FILES:
        path = DataLoader.resolve_data_path(filename)
        if Path(path).exists():
            continue
        missing_sources.append({"name": filename, "path": str(path)})
    return missing_sources

def _build_action_plan_data_unavailable_message(missing_sources):
    details = "；".join(
        f"{source.get('name')}: {source.get('path')}"
        for source in missing_sources
    )
    return (
        "行动计划数据源不可用，已跳过本次自动生成。"
        f"缺少文件：{details}。"
        "请恢复数据文件后再重新生成行动计划。"
    )

async def create_action_plan_stream(
    request: Optional[ActionPlanRequest] = None, *, staging_directory: Optional[Path] = None,
):
    run_prompt_args = []

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # Internal-only output control; it is absent from every request schema.
    env.pop("VANTAGE_ACTION_PLAN_STAGING_DIR", None)
    if staging_directory is not None:
        env["VANTAGE_ACTION_PLAN_STAGING_DIR"] = str(staging_directory)
    env["AI_REASONING_EFFORT"] = _chat._normalize_reasoning_effort(
        request.reasoning_effort if request else None,
    )
    selected_model = request.model if request else None
    selected_provider_route = request.provider_route if request else None
    selected_service_tier = _chat._normalize_service_tier(request.service_tier if request else None)
    if selected_model:
        run_prompt_args.append(f"--model={selected_model}")
    if selected_provider_route:
        run_prompt_args.append(f"--provider_route={selected_provider_route}")
    if selected_service_tier:
        run_prompt_args.append(f"--service_tier={selected_service_tier}")
        env["AI_SERVICE_TIER"] = selected_service_tier
    cmd, run_prompt_cwd = _processes._build_run_prompt_subprocess(run_prompt_args)
    replace_today = request.replace_today if request else False
    wait_for_provider_ready = bool(request.wait_for_provider_ready) if request else False
    previous_today_files = _list_today_action_plan_files() if replace_today else []

    async def process_stream():
        stderr_task = None
        stderr_lines = []
        missing_sources = _get_missing_action_plan_data_sources()
        if missing_sources:
            error_message = _build_action_plan_data_unavailable_message(missing_sources)
            logging.warning("Action plan skipped because required data sources are missing: %s", error_message)
            yield json.dumps(
                {"log": f"STREAM_ANALYSIS_ERROR:{json.dumps(error_message, ensure_ascii=False)}"},
                ensure_ascii=False,
            ) + "\n"
            return

        if wait_for_provider_ready:
            waiting_message = "等待本地反代启动，准备好后会自动开始生成行动计划。"
            yield json.dumps(
                {"log": f"STREAM_ANALYSIS_CONTENT:{json.dumps(waiting_message, ensure_ascii=False)}"},
                ensure_ascii=False,
            ) + "\n"
            readiness = await _providers._wait_for_action_plan_provider_ready(selected_provider_route)
            if not readiness.get("ready"):
                route = readiness.get("route") or selected_provider_route or "<auto>"
                base_url = readiness.get("base_url") or ""
                error = readiness.get("error") or "unknown error"
                error_message = (
                    f"本地反代还没准备好，已等待 {_providers.ACTION_PLAN_PROVIDER_READY_TIMEOUT_SECONDS} 秒。"
                    f" provider={route} base_url={base_url} error={error}"
                )
                logging.warning("Action plan provider readiness wait failed: %s", error_message)
                yield json.dumps(
                    {"log": f"STREAM_ANALYSIS_ERROR:{json.dumps(error_message, ensure_ascii=False)}"},
                    ensure_ascii=False,
                ) + "\n"
                return

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run_prompt_cwd,
                env=env
            )
            logging.info(
                "Action plan subprocess started: model=%s reasoning_effort=%s service_tier=%s replace_today=%s",
                selected_model or "<auto>",
                env["AI_REASONING_EFFORT"],
                selected_service_tier or "<none>",
                replace_today,
            )
            stderr_task = asyncio.create_task(
                _observability._drain_subprocess_stderr(proc.stderr, "action_plan", stderr_lines)
            )
            stream_failed = False

            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                decoded = _observability._decode_subprocess_chunk(line)
                if decoded.startswith(("STREAM_ANALYSIS_ERROR:", "STREAM_PLAN_ERROR:", "STREAM_ERROR:")):
                    stream_failed = True
                yield json.dumps({"log": decoded}) + "\n"

            await proc.wait()
            if stderr_task is not None:
                await stderr_task

            if proc.returncode != 0:
                err_msg = "\n".join(stderr_lines).strip() or f"run_prompt.py exited with code {proc.returncode}"
                logging.error("Action plan subprocess failed: %s", err_msg)
                yield json.dumps({"error": err_msg}) + "\n"
            elif stream_failed:
                logging.error("Action plan subprocess reported an analysis error")
            elif replace_today:
                logging.info("Action plan subprocess completed successfully; replacing today's saved files")
                _replace_today_action_plan_files(previous_today_files)
            else:
                logging.info("Action plan subprocess completed successfully")
            if proc.returncode == 0 and not stream_failed:
                yield json.dumps({"done": True}) + "\n"

        except asyncio.CancelledError:
            logging.warning("Action plan stream cancelled by client")
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
                        logging.warning("Killing orphan action plan subprocess")
                    await _processes.reap_subprocess(proc)

    return StreamingResponse(process_stream(), media_type="application/x-ndjson")

@router.get("/api/action_plan_content")
async def get_action_plan_content():
    try:
        latest_file = _get_latest_action_plan_file()
        if latest_file is None:
            return {"exists": False, "analysis": None, "plan": None, "meta": None}

        payload = _load_action_plan_payload(latest_file)
        if not payload:
            return {"exists": False, "analysis": None, "plan": None, "meta": None}

        return {
            "exists": True,
            "analysis": payload.get("analysis"),
            "plan": payload.get("plan"),
            "meta": payload.get("meta"),
            "timestamp": os.path.getctime(latest_file),
            "filename": os.path.basename(latest_file),
            "id": payload.get("id"),
        }
    except Exception as e:
        return {"error": str(e)}

# Module-qualified references keep shared state and dependency overrides live.
from . import chat as _chat
from . import observability as _observability
from . import processes as _processes
from . import providers as _providers


# Compatibility for Python integrations; HTTP generation is registered by application.py.
generate_action_plan = create_action_plan_stream
