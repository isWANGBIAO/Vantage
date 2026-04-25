import sys
import json
import argparse
import logging
import uuid
from pathlib import Path
from datetime import datetime

# Add project root to sys.path to ensure modules can be imported
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
sys.path.append(str(project_root))

from src.core.config import Config
from src.core.context import ContextManager
from src.services.llm_client import LLMClient
from src.services.audio_service import AudioService
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


def get_action_plan_round_content(result):
    if not isinstance(result, dict):
        return ""
    return (result.get("content") or "").strip()


def _sum_usage_totals(*usage_payloads):
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for usage in usage_payloads:
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key, 0) or 0
            totals[key] += int(value)
    return totals


def run_action_plan_round(
    *,
    client,
    messages,
    section,
    model_override,
    provider_route,
    emit_start_before_first_attempt,
    max_empty_content_retries=ACTION_PLAN_EMPTY_CONTENT_RETRY_COUNT,
    session_id=None,
    source="action_plan",
    entrypoint=RUN_PROMPT_ENTRYPOINT,
    context_file=None,
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

        result = client.chat(
            messages,
            stream=True,
            print_callback=build_action_plan_stream_printer(section),
            model=model_override,
            provider_route=provider_route,
            session_id=session_id,
            source=source,
            entrypoint=entrypoint,
            context_file=context_file,
        )
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


def _write_context_session_id(context_file, session_id, source):
    session_path = _get_context_session_file(context_file)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "source": source,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
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
    parser.add_argument("--chat_message", help="User message for chat mode")
    parser.add_argument("--context_file", help="Path to load context from")
    parser.add_argument("--model", help="Model name override for this run")
    parser.add_argument("--provider_route", help="Provider route override for this run")
    parser.add_argument("--client_sent_at", help="Client-side timestamp for the current chat message")
    
    args = parser.parse_args()
    model_override = args.model.strip() if args.model else None
    provider_route = args.provider_route.strip() if args.provider_route else None
    
    try:
        Config.load_env()
        history_dir = Path(Config.get_history_dir())
        
        # === TRANSCRIPT MODE ===
        if args.transcribe:
            text = AudioService.transcribe(args.transcribe)
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
                "total_duration": 0,
                "speed": "0.00 tokens/s",
                "historical_total_tokens": context_mgr.token_count
            }

            print("Thinking...")
            print("---CHAT_START---")
            
            # Send the full persisted chat history
            messages_to_send = context_mgr.get_messages()
            chat_session_id = _get_or_create_context_session_id(context_mgr.context_file, "chat")
            existing_session_summary = _load_session_usage_summary(history_dir, chat_session_id)

            initial_stats["historical_total_tokens"] = (
                existing_session_summary.get("total_tokens", 0)
                if existing_session_summary
                else context_mgr.token_count
            )
            print(f"STATS_JSON:{json.dumps(initial_stats)}")
             
            # Call API
            result = client.chat(
                messages_to_send,
                stream=True,
                model=model_override,
                provider_route=provider_route,
                session_id=chat_session_id,
                source="chat",
                entrypoint=RUN_PROMPT_ENTRYPOINT,
                context_file=str(context_mgr.context_file),
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
            duration = result.get("duration", 0)
            
            updated_session_summary = _load_session_usage_summary(history_dir, chat_session_id)

            stats_output = {
                "turns": len(context_mgr.messages), 
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "total_duration": duration,
                "speed": f"{completion_tokens / duration:.2f} tokens/s" if duration > 0 else "0.00 tokens/s",
                "historical_total_tokens": (
                    updated_session_summary.get("total_tokens", total_tokens)
                    if updated_session_summary
                    else context_mgr.token_count
                ),
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
                    days=365
                )
            
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
            initial_stats = {
                "turns": len(analysis_messages), # Estimate
                "prompt_tokens": len(prompt_text) // 4, # Rough estimate
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_duration": 0,
                "speed": "0.00 tokens/s",
                "historical_total_tokens": 0
            }

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
                emit_start_before_first_attempt=False,
                session_id=action_plan_session_id,
                source="action_plan",
                entrypoint=RUN_PROMPT_ENTRYPOINT,
                context_file=str(context_mgr.context_file),
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
                    emit_start_before_first_attempt=True,
                    session_id=action_plan_session_id,
                    source="action_plan",
                    entrypoint=RUN_PROMPT_ENTRYPOINT,
                    context_file=str(context_mgr.context_file),
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
                    _write_context_session_id(context_mgr.context_file, action_plan_session_id, "action_plan")
                    _write_context_session_id(action_plan_context_file, action_plan_session_id, "action_plan")

                    # Print Stats
                    usage1 = result.get("usage", {})
                    usage2 = result_round_2.get("usage", {})
                    
                    total_prompt_tokens = usage1.get("prompt_tokens", 0) + usage2.get("prompt_tokens", 0)
                    total_completion_tokens = usage1.get("completion_tokens", 0) + usage2.get("completion_tokens", 0)
                    total_total_tokens = usage1.get("total_tokens", 0) + usage2.get("total_tokens", 0)
                    total_duration = result.get("duration", 0) + result_round_2.get("duration", 0)
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

                    stats_output = {
                        "turns": len(context_mgr.messages),
                        "prompt_tokens": summary_prompt_tokens,
                        "completion_tokens": summary_completion_tokens,
                        "total_tokens": summary_total_tokens,
                        "total_duration": summary_total_duration,
                        "speed": (
                            f"{summary_completion_tokens / summary_total_duration:.2f} tokens/s"
                            if summary_total_duration > 0
                            else "0.00 tokens/s"
                        ),
                        "historical_total_tokens": summary_total_tokens,
                    }
                    metadata = build_generation_metadata(result, result_round_2)
                    stats_output.update(metadata)
                    print(f"STATS_JSON:{json.dumps(stats_output)}")

                    action_plan_payload = build_action_plan_payload(
                        generated_at=generated_at,
                        analysis_body=first_round_content,
                        plan_body=second_round_content,
                        stats=stats_output,
                        metadata=metadata,
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
