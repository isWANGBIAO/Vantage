import sys
import json
import argparse
import logging
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
from src.utils.data_loader import DataLoader
from src.utils.action_plan_sanitizer import sanitize_action_plan_markdown
from src.utils.action_plan_stream import (
    build_action_plan_stream_printer,
    emit_action_plan_stream_event,
)
from src.utils.generation_stats import build_generation_metadata

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

def main():
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Run AI Prompts V2 (Modular)")
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument("output_file", nargs="?", help="Path to the output file")
    parser.add_argument("--transcribe", help="Path to audio file to transcribe")
    parser.add_argument("--chat_message", help="User message for chat mode")
    parser.add_argument("--context_file", help="Path to load context from")
    parser.add_argument("--model", help="Model name override for this run")
    parser.add_argument("--client_sent_at", help="Client-side timestamp for the current chat message")
    
    args = parser.parse_args()
    model_override = args.model.strip() if args.model else None
    
    try:
        Config.load_env()
        
        # === TRANSCRIPT MODE ===
        if args.transcribe:
            text = AudioService.transcribe(args.transcribe)
            if text:
                print(f"TRANSCRIPTION_RESULT:{text}")
            else:
                print("TRANSCRIPTION_RESULT:")
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
            print(f"STATS_JSON:{json.dumps(initial_stats)}")

            print("Thinking...")
            print("---CHAT_START---")
            
            # Send the full persisted chat history
            messages_to_send = context_mgr.get_messages()
            
            # Call API
            result = client.chat(messages_to_send, stream=True, model=model_override)
            
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
            
            stats_output = {
                "turns": len(context_mgr.messages), 
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "total_duration": duration,
                "speed": f"{completion_tokens / duration:.2f} tokens/s" if duration > 0 else "0.00 tokens/s",
                "historical_total_tokens": context_mgr.token_count # Approximate
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
                    days=90
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
            action_plan_msg = None

            action_plan_prompt_path = DataLoader.resolve_data_path("Prompt_Action_Plan.md")
            if action_plan_prompt_path.exists():
                action_plan_template = action_plan_prompt_path.read_text(encoding="utf-8")
                today_data = DataLoader.get_today_data_row(DataLoader.resolve_data_path("Time.xlsx"))
                yesterday_data = DataLoader.get_yesterday_data_row(DataLoader.resolve_data_path("Time.xlsx"))
                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                action_plan_msg = action_plan_template.replace("{current_time}", current_time_str)
                action_plan_msg = action_plan_msg.replace("{today_data_row}", today_data)
                action_plan_msg = action_plan_msg.replace("{yesterday_data_row}", yesterday_data)
            
            print("正在生成初始分析报告，请稍候...")
            print("---ANALYSIS_START---")
            
            # === ROUND 1: General Analysis ===
            # Emit initial stats
            initial_stats = {
                "turns": len(analysis_messages), # Estimate
                "prompt_tokens": len(prompt_text) // 4, # Rough estimate
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_duration": 0,
                "speed": "0.00 tokens/s",
                "historical_total_tokens": 0 # New session logic in script, but maybe we can read global context? 
                # Actually, if we are in Analysis mode, we might not have loaded the global ContextManager if we initialized a new list.
                # But let's check if we can reuse context_mgr from lines 50 involved?
                # Line 50: context_mgr = ContextManager(context_file=args.context_file)
                # So we have it.
            }
            # Update historical from context_mgr if available
            if 'context_mgr' in locals():
                 initial_stats['historical_total_tokens'] = context_mgr.token_count

            print(f"STATS_JSON:{json.dumps(initial_stats)}")
            emit_action_plan_stream_event("analysis", "system", sys_content)
            emit_action_plan_stream_event("analysis", "prompt", prompt_text)
            if action_plan_msg is not None:
                emit_action_plan_stream_event("plan", "prompt", action_plan_msg)

            
            # Send initial huge context
            result = client.chat(
                analysis_messages,
                stream=True,
                print_callback=build_action_plan_stream_printer("analysis"),
                model=model_override,
            )
            
            first_round_content = result["content"]
            if first_round_content:
                # We do NOT save the full history context yet, or maybe we do?
                # For this specific dual-turn flow, let's keep it simple.
                analysis_messages.append({"role": "assistant", "content": first_round_content})
            
            # Print Stats for round 1 (Optional, but GUI might expect it at end)
            
            # === SEPARATOR FOR GUI ===
            print("---PLAN_START---")
            
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
                
                result_round_2 = client.chat(
                    analysis_messages,
                    stream=True,
                    print_callback=build_action_plan_stream_printer("plan"),
                    model=model_override,
                )
                second_round_content = result_round_2["content"]
                
                if second_round_content:
                    # Save Output to File
                    if args.output_file:
                        output_path = Path(args.output_file)
                    else:
                        history_dir = Config.get_history_dir()
                        prefix = "action_plan"
                        output_path = history_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                    
                    # Save BOTH rounds with a separator so Web UI can display both panels
                    # Format: [Analysis Content]---ANALYSIS_END---[Plan Content]
                    combined_content = (
                        first_round_content + 
                        "\n\n---ANALYSIS_END---\n\n" + 
                        second_round_content
                    )
                    output_path.write_text(sanitize_action_plan_markdown(combined_content), encoding="utf-8")
                    # print(f"\nResponse saved to: {output_path}")

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

                    # Print Stats
                    usage1 = result.get("usage", {})
                    usage2 = result_round_2.get("usage", {})
                    
                    total_prompt_tokens = usage1.get("prompt_tokens", 0) + usage2.get("prompt_tokens", 0)
                    total_completion_tokens = usage1.get("completion_tokens", 0) + usage2.get("completion_tokens", 0)
                    total_total_tokens = usage1.get("total_tokens", 0) + usage2.get("total_tokens", 0)
                    total_duration = result.get("duration", 0) + result_round_2.get("duration", 0)

                    stats_output = {
                        "turns": len(context_mgr.messages),
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_total_tokens,
                        "total_duration": total_duration,
                        "speed": f"{total_completion_tokens / total_duration:.2f} tokens/s" if total_duration > 0 else "0.00 tokens/s",
                        "historical_total_tokens": total_total_tokens
                    }
                    stats_output.update(build_generation_metadata(result, result_round_2))
                    print(f"STATS_JSON:{json.dumps(stats_output)}")

            else:
                print("Error: Prompt_Action_Plan.md not found. Skipping second round.")
            
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
