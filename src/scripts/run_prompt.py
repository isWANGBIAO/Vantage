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
from src.services.llm_client import SiliconFlowClient
from src.services.audio_service import AudioService
from src.utils.data_loader import DataLoader

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def main():
    setup_logging()
    
    parser = argparse.ArgumentParser(description="Run AI Prompts V2 (Modular)")
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument("output_file", nargs="?", help="Path to the output file")
    parser.add_argument("--transcribe", help="Path to audio file to transcribe")
    parser.add_argument("--chat_message", help="User message for chat mode")
    parser.add_argument("--context_file", help="Path to load context from")
    
    args = parser.parse_args()
    
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
        client = SiliconFlowClient()
        
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
            chat_msg = args.chat_message
            context_mgr.add_message("user", chat_msg)
            
            print("Thinking...")
            print("---CHAT_START---")
            
            # Prune context before sending
            messages_to_send = context_mgr.get_messages(prune=True)
            
            # Call API
            result = client.chat(messages_to_send, stream=True)
            
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
            
            print("正在生成初始分析报告，请稍候...")
            print("---ANALYSIS_START---")
            
            # === ROUND 1: General Analysis ===
            print("正在生成初始分析报告，请稍候...")
            print("---ANALYSIS_START---")
            
            # Send initial huge context
            result = client.chat(analysis_messages, stream=True)
            
            first_round_content = result["content"]
            if first_round_content:
                # We do NOT save the full history context yet, or maybe we do?
                # For this specific dual-turn flow, let's keep it simple.
                analysis_messages.append({"role": "assistant", "content": first_round_content})
            
            # Print Stats for round 1 (Optional, but GUI might expect it at end)
            
            # === SEPARATOR FOR GUI ===
            print("\n初始分析已完成。正在生成今日行动建议...\n")
            
            # === ROUND 2: Specific Action Plan ===
            
            # 1. Load Action Plan Template
            action_plan_prompt_path = DataLoader.resolve_data_path("Prompt_Action_Plan.md")
            if action_plan_prompt_path.exists():
                action_plan_template = action_plan_prompt_path.read_text(encoding="utf-8")
                
                # 2. Get Today's and Yesterday's Data Row
                today_data = DataLoader.get_today_data_row(DataLoader.resolve_data_path("Time.xlsx"))
                yesterday_data = DataLoader.get_yesterday_data_row(DataLoader.resolve_data_path("Time.xlsx"))
                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                
                # 3. Fill Template
                # Replace {current_time}
                action_plan_msg = action_plan_template.replace("{current_time}", current_time_str)
                # Replace {today_data_row}
                action_plan_msg = action_plan_msg.replace("{today_data_row}", today_data)
                # Replace {yesterday_data_row}
                action_plan_msg = action_plan_msg.replace("{yesterday_data_row}", yesterday_data)
                
                # [User Request] Repeat the prompt content twice for Round 2 as well
                # Handled in llm_client now
                
                # 4. Append to history
                analysis_messages.append({"role": "user", "content": action_plan_msg})
                
                # 5. Call API Again
                # Stream usage is tricky effectively. run_prompt.py streams to stdout, 
                # and the GUI reads it.
                # The GUI splits by "初始分析已完成..." so the second stream will go to the right panel.
                
                result_round_2 = client.chat(analysis_messages, stream=True)
                second_round_content = result_round_2["content"]
                
                if second_round_content:
                    # Save Output to File
                    if args.output_file:
                        output_path = Path(args.output_file)
                    else:
                        history_dir = Config.get_history_dir()
                        prefix = "action_plan"
                        output_path = history_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                    
                    # We save the SECOND round content (The Action Plan) to the file, 
                    # as that corresponds to "Action Plan" file. 
                    # Or should we save both? 
                    # Usually the daily review file is the PLAN. 
                    # Let's save the Plan.
                    output_path.write_text(second_round_content, encoding="utf-8")
                    print(f"\nResponse saved to: {output_path}")

                    # --- CRITICAL FIX: Save back to ContextManager so Chat knows what happened ---
                    # Round 1: Analysis
                    context_mgr.add_message("user", prompt_text)
                    context_mgr.add_message("assistant", first_round_content)
                    # Round 2: Plan
                    plan_prompt_text = action_plan_msg # Use the variable name from surrounding scope
                    context_mgr.add_message("user", plan_prompt_text)
                    context_mgr.add_message("assistant", second_round_content)
                    context_mgr.save()

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
                        "historical_total_tokens": context_mgr.token_count
                    }
                    print(f"STATS_JSON:{json.dumps(stats_output)}")

            else:
                print("Error: Prompt_Action_Plan.md not found. Skipping second round.")
            
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
