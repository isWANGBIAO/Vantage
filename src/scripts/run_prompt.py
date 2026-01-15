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
            
            context_mgr.add_message("user", args.chat_message)
            
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
            
            result = client.chat(analysis_messages, stream=True)
            
            # Save Output to File (Old behavior)
            base_dir = Config.get_project_root()
            if args.output_file:
                output_path = Path(args.output_file)
            else:
                history_dir = Config.get_history_dir()
                output_path = history_dir / f"model_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            
            content = result["content"]
            if content:
                output_path.write_text(content, encoding="utf-8")
                print(f"\nResponse saved to: {output_path}")
                
                print(f"\nResponse saved to: {output_path}")

            # Print Stats for GUI
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)
            duration = result.get("duration", 0)
            
            stats_output = {
                "turns": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "total_duration": duration,
                "speed": f"{completion_tokens / duration:.2f} tokens/s" if duration > 0 else "0.00 tokens/s",
                "historical_total_tokens": total_tokens # simplified
            }
            print(f"STATS_JSON:{json.dumps(stats_output)}")
            # or it did?
            # Original: 
            # if args.chat_message: save_context...
            # if normal mode: just plain print and save to output file.
            # So we do NOT save to context file in this mode to avoid polluting chat history with huge reports.
            
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
