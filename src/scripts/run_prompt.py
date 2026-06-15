import sys
import json
import argparse
import logging
import uuid
import os
from pathlib import Path
from datetime import datetime

# Add project root to sys.path to ensure modules can be imported
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
sys.path.append(str(project_root))

from src.core.config import Config
from src.core.context import ContextManager
from src.services.llm_client import LLMClient, StreamIncompleteError
from src.services.audio_service import AudioService, AudioTranscriptionError
from src.services.model_call_recorder import get_session_usage_summary
from src.utils.data_loader import DataLoader
from src.utils.action_plan_sanitizer import sanitize_action_plan_markdown
from src.utils.action_plan_stream import (
    build_action_plan_stream_printer,
    emit_action_plan_stream_event,
)
from src.utils.generation_stats import build_generation_metadata


ACTION_PLAN_EMPTY_CONTENT_RETRY_COUNT = 1
RUN_PROMPT_ENTRYPOINT = "src/scripts/run_prompt.py"
ACTION_PLAN_TIME_SERIES_START_DATE = "2025-01-01"
ACTION_PLAN_PROXY_PROMPT_TOKEN_LIMIT = 250_000
ACTION_PLAN_DEFAULT_BALANCE_SHEET_ROW_LIMIT_PER_SHEET = 100
ACTION_PLAN_SJTU_TIME_SERIES_DAYS = 14
ACTION_PLAN_SJTU_BALANCE_SHEET_ROW_LIMIT_PER_SHEET = 8


def _load_session_usage_summary(history_dir, session_id):
    if not session_id:
        return None

    try:
        return get_session_usage_summary(
            session_id,
            db_file=Path(history_dir) / "state.db",
        )
    except Exception as error:
        logging.warning("Failed to load session usage summary for %s: %s", session_id, error)
        return None

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def format_chat_message_with_timestamp(message, raw_timestamp):
    if not raw_timestamp:
        return message

    timestamp_text = str(raw_timestamp).strip()
    if not timestamp_text:
        return message

    try:
        parsed_timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
        timestamp_text = parsed_timestamp.isoformat(sep=" ", timespec="seconds")
    except ValueError:
        pass

    return f"[Message timestamp: {timestamp_text}]\n{message}"


def _load_context_messages_file(path):
    context_path = Path(path)
    if not context_path.exists():
        return []

    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    return payload if isinstance(payload, list) else []


def _message_prefix_matches(messages, prefix):
    if not prefix or len(messages or []) < len(prefix):
        return False
    return list(messages[:len(prefix)]) == list(prefix)


def build_chat_request_messages(full_history, *, action_plan_messages=None):
    history_messages = list(full_history or [])
    stable_prefix = list(action_plan_messages or [])
    if not stable_prefix:
        return history_messages
    if _message_prefix_matches(history_messages, stable_prefix):
        return history_messages
    return stable_prefix + history_messages


def get_action_plan_round_content(result):
    if not isinstance(result, dict):
        return ""
    return (result.get("content") or "").strip()


def _sum_usage_totals(*usage_payloads):
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "completion_reasoning_tokens": 0,
    }
    for usage in usage_payloads:
        if not isinstance(usage, dict):
            continue
        normalized_cache_hit = usage.get("prompt_cache_hit_tokens")
        if normalized_cache_hit is None:
            prompt_details = usage.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                normalized_cache_hit = prompt_details.get("cached_tokens")
        normalized_cache_miss = usage.get("prompt_cache_miss_tokens")
        if normalized_cache_miss is None and normalized_cache_hit is not None:
            normalized_cache_miss = max(int(usage.get("prompt_tokens", 0) or 0) - int(normalized_cache_hit or 0), 0)
        normalized_reasoning = usage.get("completion_reasoning_tokens")
        if normalized_reasoning is None:
            completion_details = usage.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                normalized_reasoning = completion_details.get("reasoning_tokens")

        usage_with_normalized_fields = {
            **usage,
            "prompt_cache_hit_tokens": normalized_cache_hit,
            "prompt_cache_miss_tokens": normalized_cache_miss,
            "completion_reasoning_tokens": normalized_reasoning,
        }
        for key in totals:
            value = usage_with_normalized_fields.get(key)
            if value is None:
                continue
            totals[key] += int(value or 0)
    return totals


def _as_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_prompt_context_limit_metadata(*, prompt_tokens=None, estimated_prompt_tokens=None):
    observed_values = []
    for value in (prompt_tokens, estimated_prompt_tokens):
        if value is None:
            continue
        try:
            observed_values.append(int(float(value)))
        except (TypeError, ValueError):
            continue
    observed_prompt_tokens = max(observed_values) if observed_values else None
    exceeded = (
        observed_prompt_tokens is not None
        and observed_prompt_tokens > ACTION_PLAN_PROXY_PROMPT_TOKEN_LIMIT
    )
    warning = None
    if exceeded:
        warning = {
            "code": "prompt_context_limit_exceeded",
            "limit": ACTION_PLAN_PROXY_PROMPT_TOKEN_LIMIT,
            "prompt_tokens": prompt_tokens,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "observed_prompt_tokens": observed_prompt_tokens,
        }

    return {
        "prompt_token_limit": ACTION_PLAN_PROXY_PROMPT_TOKEN_LIMIT,
        "prompt_token_limit_exceeded": exceeded,
        "prompt_context_warning": warning,
    }


def _build_prompt_context_limit_summary(request_stats):
    request_warnings = [
        request.get("prompt_context_warning")
        for request in request_stats or []
        if request.get("prompt_token_limit_exceeded")
    ]
    request_warnings = [warning for warning in request_warnings if isinstance(warning, dict)]
    warning = None
    if request_warnings:
        warning = max(
            request_warnings,
            key=lambda item: int(item.get("observed_prompt_tokens") or 0),
        )

    return {
        "prompt_token_limit": ACTION_PLAN_PROXY_PROMPT_TOKEN_LIMIT,
        "prompt_token_limit_exceeded": warning is not None,
        "prompt_context_warning": warning,
    }


def build_action_plan_request_stats(section, result):
    payload = dict(result or {})
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    duration = float(payload.get("duration", 0) or 0)
    usage_recorded = any(
        usage.get(key) is not None
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
            "completion_reasoning_tokens",
        )
    ) or isinstance(usage.get("prompt_tokens_details"), dict) or isinstance(usage.get("completion_tokens_details"), dict)
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0) if usage_recorded else None
    completion_tokens = int(usage.get("completion_tokens", 0) or 0) if usage_recorded else None
    total_tokens = int(usage.get("total_tokens", 0) or 0) if usage_recorded else None
    prompt_cache_hit_tokens = usage.get("prompt_cache_hit_tokens")
    if prompt_cache_hit_tokens is None:
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            prompt_cache_hit_tokens = prompt_details.get("cached_tokens")
    prompt_cache_miss_tokens = usage.get("prompt_cache_miss_tokens")
    if prompt_cache_miss_tokens is None and prompt_cache_hit_tokens is not None:
        prompt_cache_miss_tokens = max(int(prompt_tokens or 0) - int(prompt_cache_hit_tokens or 0), 0)
    completion_reasoning_tokens = usage.get("completion_reasoning_tokens")
    if completion_reasoning_tokens is None:
        completion_details = usage.get("completion_tokens_details")
        if isinstance(completion_details, dict):
            completion_reasoning_tokens = completion_details.get("reasoning_tokens")
    cache_total = int(prompt_cache_hit_tokens or 0) + int(prompt_cache_miss_tokens or 0)
    if not usage_recorded:
        prompt_cache_hit_tokens = None
        prompt_cache_miss_tokens = None
        completion_reasoning_tokens = None
        cache_total = 0
    completion_rate = int(completion_tokens or 0) / duration if usage_recorded and duration > 0 else None
    total_rate = int(total_tokens or 0) / duration if usage_recorded and duration > 0 else None

    stats = {
        "section": section,
        "duration": duration,
        "completed_at": payload.get("completed_at"),
        "first_token_latency": _as_float_or_none(payload.get("first_token_latency")),
        "usage_recorded": usage_recorded,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": prompt_cache_miss_tokens,
        "prompt_cache_hit_rate": (int(prompt_cache_hit_tokens or 0) / cache_total * 100) if cache_total else None,
        "completion_reasoning_tokens": completion_reasoning_tokens,
        "completion_tokens_per_second": completion_rate,
        "total_tokens_per_second": total_rate,
        "output_tokens_per_second": completion_rate,
        "average_tokens_per_second": total_rate,
        "model": payload.get("model"),
        "provider_route": payload.get("provider_route"),
        "requested_model": payload.get("requested_model"),
        "requested_provider_route": payload.get("requested_provider_route"),
        "fallback_used": bool(payload.get("fallback_used")),
        "reasoning_effort": payload.get("reasoning_effort") or "medium",
        "service_tier": payload.get("service_tier"),
        "attempts": int(payload.get("attempts", 1) or 1),
    }
    stats.update(_build_prompt_context_limit_metadata(prompt_tokens=prompt_tokens))
    return stats


def _first_non_null(*values):
    for value in values:
        normalized = _as_float_or_none(value)
        if normalized is not None:
            return normalized
    return None


def _uses_sjtu_provider(provider_route):
    return str(provider_route or "").strip().lower() == "sjtu"


def _build_action_plan_prompt_kwargs(provider_route):
    if _uses_sjtu_provider(provider_route):
        return {
            "days": ACTION_PLAN_SJTU_TIME_SERIES_DAYS,
            "start_date": None,
            "balance_sheet_row_limit_per_sheet": ACTION_PLAN_SJTU_BALANCE_SHEET_ROW_LIMIT_PER_SHEET,
        }
    return {
        "start_date": ACTION_PLAN_TIME_SERIES_START_DATE,
        "balance_sheet_row_limit_per_sheet": ACTION_PLAN_DEFAULT_BALANCE_SHEET_ROW_LIMIT_PER_SHEET,
    }


def run_action_plan_round(
    *,
    client,
    messages,
    section,
    model_override,
    provider_route,
    service_tier,
    emit_start_before_first_attempt,
    max_empty_content_retries=ACTION_PLAN_EMPTY_CONTENT_RETRY_COUNT,
    session_id=None,
    source="action_plan",
    entrypoint=RUN_PROMPT_ENTRYPOINT,
    context_file=None,
    metadata=None,
):
    total_attempts = max_empty_content_retries + 1
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    total_duration = 0.0
    last_result = {}

    for attempt in range(1, total_attempts + 1):
        if emit_start_before_first_attempt or attempt > 1:
            emit_action_plan_stream_event(section, "start", "")

        try:
            result = client.chat(
                messages,
                stream=True,
                print_callback=build_action_plan_stream_printer(section),
                model=model_override,
                provider_route=provider_route,
                service_tier=service_tier,
                session_id=session_id,
                source=source,
                entrypoint=entrypoint,
                context_file=context_file,
                metadata=metadata,
            )
        except StreamIncompleteError:
            if attempt < total_attempts:
                logging.warning(
                    "Action plan %s round stream ended incomplete on attempt %s/%s; retrying same round",
                    section,
                    attempt,
                    total_attempts,
                )
                continue
            logging.error(
                "Action plan %s round stream ended incomplete after %s attempts",
                section,
                total_attempts,
            )
            raise
        last_result = dict(result or {})
        total_usage = _sum_usage_totals(total_usage, last_result.get("usage"))
        total_duration += float(last_result.get("duration", 0) or 0)

        content = get_action_plan_round_content(last_result)
        if content:
            last_result["usage"] = total_usage
            last_result["duration"] = total_duration
            last_result["attempts"] = attempt
            return last_result, content

        if attempt < total_attempts:
            logging.warning(
                "Action plan %s round returned empty content on attempt %s/%s; retrying same round",
                section,
                attempt,
                total_attempts,
            )

    last_result["usage"] = total_usage
    last_result["duration"] = total_duration
    last_result["attempts"] = total_attempts
    logging.error(
        "Action plan %s round returned empty content after %s attempts",
        section,
        total_attempts,
    )
    return last_result, ""


def build_action_plan_payload(
    *,
    generated_at: datetime,
    analysis_body: str,
    plan_body: str,
    stats: dict,
    metadata: dict,
    input_payload: dict | None = None,
):
    timestamp_id = generated_at.strftime("%Y%m%d_%H%M%S")
    normalized_stats = dict(stats or {})
    normalized_metadata = dict(metadata or {})

    return {
        "id": timestamp_id,
        "date": generated_at.strftime("%Y-%m-%d"),
        "analysis": {
            "body": sanitize_action_plan_markdown(analysis_body),
        },
        "plan": {
            "body": sanitize_action_plan_markdown(plan_body),
        },
        "meta": {
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "model": normalized_metadata.get("model"),
            "provider_route": normalized_metadata.get("provider_route"),
            "requested_model": normalized_metadata.get("requested_model"),
            "requested_provider_route": normalized_metadata.get("requested_provider_route"),
            "fallback_used": bool(normalized_metadata.get("fallback_used")),
            "reasoning_effort": normalized_metadata.get("reasoning_effort") or "medium",
            "input": dict(input_payload or {}),
            "stats": normalized_stats,
        },
    }


def _get_context_session_file(context_file):
    context_path = Path(context_file)
    return context_path.with_name(f"{context_path.stem}_session.json")


def _read_context_session_id(context_file):
    session_path = _get_context_session_file(context_file)
    if not session_path.exists():
        return None

    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    session_id = payload.get("session_id")
    return str(session_id).strip() if session_id else None


def _write_context_session_id(context_file, session_id, source, **metadata):
    session_path = _get_context_session_file(context_file)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "source": source,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    for key, value in metadata.items():
        if value is not None:
            payload[key] = value
    session_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _get_or_create_context_session_id(context_file, source):
    session_id = _read_context_session_id(context_file)
    if session_id:
        return session_id

    session_id = str(uuid.uuid4())
    _write_context_session_id(context_file, session_id, source)
    return session_id


def _create_new_context_session_id(context_file, source):
    session_id = str(uuid.uuid4())
    _write_context_session_id(context_file, session_id, source)
    return session_id

def main():
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Run AI Prompts V2 (Modular)")
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument("output_file", nargs="?", help="Path to the output file")
    parser.add_argument("--transcribe", help="Path to audio file to transcribe")
    parser.add_argument("--transcribe-base-url", help="Voice transcription provider base URL")
    parser.add_argument("--transcribe-api-key", help="Voice transcription provider API key")
    parser.add_argument("--transcribe-model", help="Voice transcription model name")
    parser.add_argument("--chat_message", help="User message for chat mode")
    parser.add_argument("--context_file", help="Path to load context from")
    parser.add_argument("--model", help="Model name override for this run")
    parser.add_argument("--provider_route", help="Provider route override for this run")
    parser.add_argument("--service_tier", help="Service tier override for this run")
    parser.add_argument("--client_sent_at", help="Client-side timestamp for the current chat message")
    
    args = parser.parse_args()
    model_override = args.model.strip() if args.model else None
    provider_route = args.provider_route.strip() if args.provider_route else None
    service_tier = args.service_tier.strip() if args.service_tier else None
    
    try:
        Config.load_env()
        if not service_tier:
            service_tier = (Config.get("AI_SERVICE_TIER") or "").strip() or None
        history_dir = Path(Config.get_history_dir())
        
        # === TRANSCRIPT MODE ===
        if args.transcribe:
            try:
                text = AudioService.transcribe(
                    args.transcribe,
                    base_url=args.transcribe_base_url,
                    api_key=args.transcribe_api_key or os.environ.get("VANTAGE_TRANSCRIBE_API_KEY"),
                    model=args.transcribe_model,
                )
            except AudioTranscriptionError as exc:
                print(f"TRANSCRIPTION_ERROR:{exc}")
                raise SystemExit(1) from exc
            if text is None:
                print("TRANSCRIPTION_ERROR:Audio transcription failed")
                raise SystemExit(1)
            print(f"TRANSCRIPTION_RESULT:{text}")
            return

        context_mgr = ContextManager(context_file=args.context_file)
        client = LLMClient()
        
        # === CHAT MODE ===
        if args.chat_message:
            logging.info("Mode: Chat")
            
            # Ensure System Prompt is present if context is empty
            if not context_mgr.messages:
                sys_content = DataLoader.get_system_prompt_content()
                context_mgr.add_message("system", sys_content)
            
            # Update System Prompt time if it exists (Optional improvement)
            # For now, let's just stick to adding user message
            
            # [User Request] Repeat the chat message twice to emphasize it
            chat_msg = format_chat_message_with_timestamp(args.chat_message, args.client_sent_at)
            context_mgr.add_message("user", chat_msg)
            
            # Emit initial stats (Historical only)
            initial_stats = {
                "turns": len(context_mgr.messages),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "prompt_cache_hit_tokens": None,
                "prompt_cache_miss_tokens": None,
                "prompt_cache_hit_rate": None,
                "completion_reasoning_tokens": None,
                "total_duration": 0,
                "speed": "0.00 tokens/s",
                "first_token_latency": None,
                "cache_scope": "request",
            }

            print("Thinking...")
            print("---CHAT_START---")
            
            full_history_messages = context_mgr.get_messages()
            action_plan_context_file = context_mgr.context_file.parent / "latest_action_plan_context.json"
            action_plan_messages = _load_context_messages_file(action_plan_context_file)
            messages_to_send = build_chat_request_messages(
                full_history_messages,
                action_plan_messages=action_plan_messages,
            )
            chat_session_id = _get_or_create_context_session_id(context_mgr.context_file, "chat")
            chat_metadata = {
                "context_strategy": (
                    "action_plan_prefix_full_history"
                    if action_plan_messages
                    else "full_history"
                ),
                "full_context_message_count": len(full_history_messages),
                "sent_context_message_count": len(messages_to_send),
                "action_plan_context_message_count": len(action_plan_messages),
                "summary_used": False,
                "pruned": False,
            }

            print(f"STATS_JSON:{json.dumps(initial_stats)}")
             
            # Call API
            result = client.chat(
                messages_to_send,
                stream=True,
                model=model_override,
                provider_route=provider_route,
                service_tier=service_tier,
                session_id=chat_session_id,
                source="chat",
                entrypoint=RUN_PROMPT_ENTRYPOINT,
                context_file=str(context_mgr.context_file),
                metadata=chat_metadata,
            )
            
            # Handle Result
            content = result["content"]
            if content:
                context_mgr.add_message("assistant", content)
                context_mgr.save()
            else:
                logging.error("No content returned from API")

            # Print Stats for GUI
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            prompt_cache_hit_tokens = usage.get("prompt_cache_hit_tokens")
            if prompt_cache_hit_tokens is None:
                prompt_details = usage.get("prompt_tokens_details")
                if isinstance(prompt_details, dict):
                    prompt_cache_hit_tokens = prompt_details.get("cached_tokens")
            prompt_cache_miss_tokens = usage.get("prompt_cache_miss_tokens")
            if prompt_cache_miss_tokens is None and prompt_cache_hit_tokens is not None:
                prompt_cache_miss_tokens = max(int(prompt_tokens or 0) - int(prompt_cache_hit_tokens or 0), 0)
            completion_reasoning_tokens = usage.get("completion_reasoning_tokens")
            if completion_reasoning_tokens is None:
                completion_details = usage.get("completion_tokens_details")
                if isinstance(completion_details, dict):
                    completion_reasoning_tokens = completion_details.get("reasoning_tokens")
            cache_total = int(prompt_cache_hit_tokens or 0) + int(prompt_cache_miss_tokens or 0)
            duration = result.get("duration", 0)
            
            stats_output = {
                "turns": len(context_mgr.messages), 
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_cache_hit_tokens": prompt_cache_hit_tokens,
                "prompt_cache_miss_tokens": prompt_cache_miss_tokens,
                "prompt_cache_hit_rate": (
                    int(prompt_cache_hit_tokens or 0) / cache_total * 100
                    if cache_total
                    else None
                ),
                "completion_reasoning_tokens": completion_reasoning_tokens,
                "total_duration": duration,
                "speed": f"{completion_tokens / duration:.2f} tokens/s" if duration > 0 else "0.00 tokens/s",
                "first_token_latency": _as_float_or_none(result.get("first_token_latency")),
                "cache_scope": "request",
            }
            stats_output.update(build_generation_metadata(result))
            print(f"STATS_JSON:{json.dumps(stats_output)}")

        # === PROMPT/ANALYSIS MODE ===
        else:
            logging.info("Mode: Analysis/Prompt")
            
            # Construct Prompt
            if args.prompt_file:
                prompt_path = Path(args.prompt_file)
                prompt_text = prompt_path.read_text(encoding="utf-8")
            else:
                prompt_text = DataLoader.construct_prompt(
                    DataLoader.resolve_data_path("Prompt_Personal_Info.md"),
                    DataLoader.resolve_data_path("Time.xlsx"),
                    **_build_action_plan_prompt_kwargs(provider_route),
                )
            prompt_cache_metadata = DataLoader.build_prompt_cache_metadata(prompt_text)
            
            # [User Request] Repeat the prompt content twice to emphasize it
            # Handled in llm_client now
            
            # Clear previous context for fresh analysis? 
            # Original script seemed to start fresh in "Normal Mode" but didn't explicitly clear if context file wasn't passed.
            # But here we are using a persistent ContextManager by default.
            # Let's create a *fresh* session for analysis to match original behavior, 
            # or maybe we should just append? 
            # Original behavior:
            # "current_messages = [] ... add system ... add user"
            # So it does NOT use previous context.
            
            analysis_messages = []
            sys_content = DataLoader.get_system_prompt_content()
            analysis_messages.append({"role": "system", "content": sys_content})
            analysis_messages.append({"role": "user", "content": prompt_text})
            action_plan_session_id = _create_new_context_session_id(context_mgr.context_file, "action_plan")
            action_plan_msg = None

            action_plan_prompt_path = DataLoader.resolve_data_path("Prompt_Action_Plan.md")
            if action_plan_prompt_path.exists():
                action_plan_template = action_plan_prompt_path.read_text(encoding="utf-8")
                time_data_path = DataLoader.resolve_data_path("Time.xlsx")
                past_7_days_rows = DataLoader.get_past_seven_days_rows(time_data_path)
                today_data = DataLoader.get_today_data_row(time_data_path)
                yesterday_data = DataLoader.get_yesterday_data_row(time_data_path)
                future_planned_rows = DataLoader.get_future_planned_rows(time_data_path)
                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                action_plan_msg = action_plan_template.replace("{current_time}", current_time_str)
                if "{past_7_days_rows}" in action_plan_msg:
                    action_plan_msg = action_plan_msg.replace("{past_7_days_rows}", past_7_days_rows)
                else:
                    action_plan_msg = f"{action_plan_msg}\n\n{past_7_days_rows}"
                action_plan_msg = action_plan_msg.replace("{today_data_row}", today_data)
                action_plan_msg = action_plan_msg.replace("{yesterday_data_row}", yesterday_data)
                if "{future_planned_rows}" in action_plan_msg:
                    action_plan_msg = action_plan_msg.replace("{future_planned_rows}", future_planned_rows)
                else:
                    action_plan_msg = f"{action_plan_msg}\n\n{future_planned_rows}"
            
            print("正在生成初始分析报告，请稍候...")
            # === ROUND 1: General Analysis ===
            # Emit initial stats
            estimated_prompt_tokens = max(len(prompt_text), len(prompt_text) // 4)
            initial_stats = {
                "turns": len(analysis_messages), # Estimate
                "prompt_tokens": len(prompt_text) // 4, # Rough estimate
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_duration": 0,
                "speed": "0.00 tokens/s",
                "first_token_latency": None,
                "requests": [],
            }
            initial_stats.update(_build_prompt_context_limit_metadata(
                estimated_prompt_tokens=estimated_prompt_tokens,
            ))

            print(f"STATS_JSON:{json.dumps(initial_stats)}")
            emit_action_plan_stream_event("analysis", "start", "")
            emit_action_plan_stream_event("analysis", "system", sys_content)
            emit_action_plan_stream_event("analysis", "prompt", prompt_text)
            if action_plan_msg is not None:
                emit_action_plan_stream_event("plan", "prompt", action_plan_msg)

            
            result, first_round_content = run_action_plan_round(
                client=client,
                messages=analysis_messages,
                section="analysis",
                model_override=model_override,
                provider_route=provider_route,
                service_tier=service_tier,
                emit_start_before_first_attempt=False,
                session_id=action_plan_session_id,
                source="action_plan",
                entrypoint=RUN_PROMPT_ENTRYPOINT,
                context_file=str(context_mgr.context_file),
                metadata={
                    **prompt_cache_metadata,
                    "cache_section": "analysis",
                    "service_tier": service_tier,
                },
            )
            if first_round_content:
                # We do NOT save the full history context yet, or maybe we do?
                # For this specific dual-turn flow, let's keep it simple.
                analysis_messages.append({"role": "assistant", "content": first_round_content})
            
            # Print Stats for round 1 (Optional, but GUI might expect it at end)
            
            # === ROUND 2: Specific Action Plan ===
            
            if action_plan_msg is not None:
                # [User Request] Repeat the prompt content twice for Round 2 as well
                # Handled in llm_client now
                
                # 1. Append to history
                analysis_messages.append({"role": "user", "content": action_plan_msg})
                
                # 2. Call API Again
                # Stream usage is tricky effectively. run_prompt.py streams to stdout, 
                # and the GUI reads it.
                # The GUI splits by "初始分析已完成..." so the second stream will go to the right panel.
                
                result_round_2, second_round_content = run_action_plan_round(
                    client=client,
                    messages=analysis_messages,
                    section="plan",
                    model_override=model_override,
                    provider_route=provider_route,
                    service_tier=service_tier,
                    emit_start_before_first_attempt=True,
                    session_id=action_plan_session_id,
                    source="action_plan",
                    entrypoint=RUN_PROMPT_ENTRYPOINT,
                    context_file=str(context_mgr.context_file),
                    metadata={
                        **prompt_cache_metadata,
                        "cache_section": "plan",
                        "service_tier": service_tier,
                    },
                )
                
                if first_round_content and second_round_content:
                    generated_at = datetime.now()

                    # --- CRITICAL FIX: Reset Context for Chat ---
                    # The user wants the Chat to start with ONLY the context of this Action Plan session.
                    # So we clear the old context and save the messages from this session.
                    context_mgr.messages = [] # Clear existing history
                    
                    # Add all messages from the analysis session (System, User1, Assistant1, User2)
                    for msg in analysis_messages:
                        context_mgr.add_message(msg['role'], msg['content'])
                    
                    # Add the final response (Assistant2)
                    context_mgr.add_message("assistant", second_round_content)
                    
                    context_mgr.save()
                    action_plan_context_file = context_mgr.context_file.parent / "latest_action_plan_context.json"
                    action_plan_context_file.write_text(
                        json.dumps(context_mgr.messages, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    action_plan_session_metadata = {
                        "model": result_round_2.get("model") or result.get("model"),
                        "provider_route": result_round_2.get("provider_route") or result.get("provider_route"),
                        "requested_model": result_round_2.get("requested_model") or result.get("requested_model"),
                        "requested_provider_route": (
                            result_round_2.get("requested_provider_route")
                            or result.get("requested_provider_route")
                        ),
                        "reasoning_effort": (
                            result_round_2.get("reasoning_effort")
                            or result.get("reasoning_effort")
                        ),
                        "service_tier": (
                            result_round_2.get("service_tier")
                            or result.get("service_tier")
                        ),
                    }
                    _write_context_session_id(
                        context_mgr.context_file,
                        action_plan_session_id,
                        "action_plan",
                        **action_plan_session_metadata,
                    )
                    _write_context_session_id(
                        action_plan_context_file,
                        action_plan_session_id,
                        "action_plan",
                        **action_plan_session_metadata,
                    )

                    # Print Stats
                    usage1 = result.get("usage", {})
                    usage2 = result_round_2.get("usage", {})
                    
                    total_prompt_tokens = usage1.get("prompt_tokens", 0) + usage2.get("prompt_tokens", 0)
                    total_completion_tokens = usage1.get("completion_tokens", 0) + usage2.get("completion_tokens", 0)
                    total_total_tokens = usage1.get("total_tokens", 0) + usage2.get("total_tokens", 0)
                    total_duration = result.get("duration", 0) + result_round_2.get("duration", 0)
                    total_cache_usage = _sum_usage_totals(usage1, usage2)
                    session_summary = _load_session_usage_summary(history_dir, action_plan_session_id)

                    summary_prompt_tokens = (
                        session_summary.get("prompt_tokens", total_prompt_tokens)
                        if session_summary
                        else total_prompt_tokens
                    )
                    summary_completion_tokens = (
                        session_summary.get("completion_tokens", total_completion_tokens)
                        if session_summary
                        else total_completion_tokens
                    )
                    summary_total_tokens = (
                        session_summary.get("total_tokens", total_total_tokens)
                        if session_summary
                        else total_total_tokens
                    )
                    summary_total_duration = (
                        session_summary.get("total_duration", total_duration)
                        if session_summary
                        else total_duration
                    )
                    summary_cache_hit_tokens = (
                        session_summary.get("prompt_cache_hit_tokens", total_cache_usage["prompt_cache_hit_tokens"])
                        if session_summary
                        else total_cache_usage["prompt_cache_hit_tokens"]
                    )
                    summary_cache_miss_tokens = (
                        session_summary.get("prompt_cache_miss_tokens", total_cache_usage["prompt_cache_miss_tokens"])
                        if session_summary
                        else total_cache_usage["prompt_cache_miss_tokens"]
                    )
                    summary_reasoning_tokens = (
                        session_summary.get("completion_reasoning_tokens", total_cache_usage["completion_reasoning_tokens"])
                        if session_summary
                        else total_cache_usage["completion_reasoning_tokens"]
                    )
                    request_stats = [
                        build_action_plan_request_stats("analysis", result),
                        build_action_plan_request_stats("plan", result_round_2),
                    ]
                    summary_cache_recorded = any(
                        request.get("prompt_cache_hit_tokens") is not None
                        or request.get("prompt_cache_miss_tokens") is not None
                        for request in request_stats
                    ) or (
                        bool(session_summary)
                        and session_summary.get("prompt_cache_hit_rate") is not None
                    )
                    if not summary_cache_recorded:
                        summary_cache_hit_tokens = None
                        summary_cache_miss_tokens = None
                    summary_cache_total = int(summary_cache_hit_tokens or 0) + int(summary_cache_miss_tokens or 0)

                    stats_output = {
                        "turns": len(context_mgr.messages),
                        "prompt_tokens": summary_prompt_tokens,
                        "completion_tokens": summary_completion_tokens,
                        "total_tokens": summary_total_tokens,
                        "prompt_cache_hit_tokens": summary_cache_hit_tokens,
                        "prompt_cache_miss_tokens": summary_cache_miss_tokens,
                        "prompt_cache_hit_rate": (
                            int(summary_cache_hit_tokens or 0) / summary_cache_total * 100
                            if summary_cache_total
                            else None
                        ),
                        "completion_reasoning_tokens": summary_reasoning_tokens,
                        "total_duration": summary_total_duration,
                        "cache_scope": "session",
                        "speed": (
                            f"{summary_completion_tokens / summary_total_duration:.2f} tokens/s"
                            if summary_total_duration > 0
                            else "0.00 tokens/s"
                        ),
                        "first_token_latency": _first_non_null(
                            request_stats[0].get("first_token_latency"),
                            request_stats[1].get("first_token_latency"),
                        ),
                        "requests": request_stats,
                    }
                    stats_output.update(_build_prompt_context_limit_summary(request_stats))
                    metadata = build_generation_metadata(result, result_round_2)
                    stats_output.update(metadata)
                    print(f"STATS_JSON:{json.dumps(stats_output)}")

                    action_plan_payload = build_action_plan_payload(
                        generated_at=generated_at,
                        analysis_body=first_round_content,
                        plan_body=second_round_content,
                        stats=stats_output,
                        metadata=metadata,
                        input_payload={
                            "system_prompt": sys_content,
                            "analysis_prompt": prompt_text,
                            "plan_prompt": action_plan_msg,
                        },
                    )

                    if args.output_file:
                        output_path = Path(args.output_file)
                    else:
                        history_dir = Config.get_history_dir()
                        output_path = history_dir / f"action_plan_{generated_at.strftime('%Y%m%d_%H%M%S')}.json"

                    output_path.write_text(
                        json.dumps(action_plan_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                else:
                    logging.error(
                        "Action plan generation incomplete: analysis_has_content=%s plan_has_content=%s",
                        bool(first_round_content),
                        bool(second_round_content),
                    )

            else:
                print("Error: Prompt_Action_Plan.md not found. Skipping second round.")
            
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
