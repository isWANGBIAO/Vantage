import os
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import shutil
import tempfile
import subprocess
import time
import json



def load_env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            val = value.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            os.environ[key] = val


def get_history_dir(base_dir):
    history_dir = base_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


def load_stats(base_dir):
    history_dir = get_history_dir(base_dir)
    stats_file = history_dir / "token_stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_conversations": 0,
        "last_updated": None
    }


def save_stats(base_dir, stats):
    history_dir = get_history_dir(base_dir)
    stats_file = history_dir / "token_stats.json"
    stats['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def generate_usage_report(base_dir, current_usage, historical_stats, model_name):
    history_dir = get_history_dir(base_dir)
    report_file = history_dir / "usage_report.md"
    
    report_content = f"""# Token Usage Report
    
## Model Information
- **Model**: {model_name}
- **Last Updated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Current Session Usage
- **Prompt Tokens**: {current_usage['prompt_tokens']}
- **Completion Tokens**: {current_usage['completion_tokens']}
- **Total Tokens**: {current_usage['total_tokens']}
- **Conversation Turns**: {current_usage['turns']}

## Historical Usage (Total)
- **Total Prompt Tokens**: {historical_stats['total_prompt_tokens']}
- **Total Completion Tokens**: {historical_stats['total_completion_tokens']}
- **Total Tokens**: {historical_stats['total_prompt_tokens'] + historical_stats['total_completion_tokens']}
- **Total Conversations**: {historical_stats['total_conversations']}
"""
    report_file.write_text(report_content, encoding='utf-8')
    return report_file


def resolve_data_root():
    env_root = os.environ.get("AI_DATA_ROOT") or os.environ.get("DATA_ROOT")
    if env_root:
        return Path(env_root)

    candidates = [
        Path(r"C:\Users\97012\OneDrive\Mine"),
        Path("/mnt/c/Users/97012/OneDrive/Mine"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path.cwd()


def resolve_data_path(filename):
    root = resolve_data_root()
    path = root / filename
    if path.exists():
        return path
    fallback = Path.cwd() / filename
    if fallback.exists():
        return fallback
    return path


def load_excel_data(excel_file_path):
    excel_file_path = Path(excel_file_path)
    if not excel_file_path.exists():
        raise FileNotFoundError(f"未找到 Excel 文件: {excel_file_path}")

    # Create a temporary copy of the Excel file to avoid PermissionError if it's open
    temp_dir = Path(tempfile.gettempdir())
    temp_excel_path = temp_dir / f"temp_read_{datetime.now().strftime('%f')}.xlsx"
    
    try:
        # Use PowerShell Copy-Item which might be more robust
        ps_cmd = [
            "powershell", 
            "-NoProfile", 
            "-Command", 
            f"Copy-Item -Path '{str(excel_file_path)}' -Destination '{str(temp_excel_path)}' -Force"
        ]
        subprocess.run(ps_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        df = pd.read_excel(temp_excel_path, engine="openpyxl")
    finally:
        if temp_excel_path.exists():
            try:
                os.remove(temp_excel_path)
            except Exception:
                pass
    
    if "日期" not in df.columns:
        raise KeyError(f"Excel中缺少'日期'列: {excel_file_path}")
    
    df["日期"] = pd.to_datetime(df["日期"])
    return df


def extract_recent_data_and_combine(prompt_file_path, excel_file_path, days=30):
    prompt_file_path = Path(prompt_file_path)
    excel_file_path = Path(excel_file_path)
    project_mgmt_path = resolve_data_path("Prompt_Project_Management.md")

    if not prompt_file_path.exists():
        raise FileNotFoundError(f"未找到 Prompt 文件: {prompt_file_path}")
    
    df = load_excel_data(excel_file_path)

    prompt_content = prompt_file_path.read_text(encoding="utf-8")

    all_columns = [col for col in df.columns if col != "日期"]

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    filtered_df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]
    filtered_df = filtered_df.sort_values(by="日期")

    data_summary = f"## 最近{days}天数据概览\n\n"
    data_summary += (
        f"查询时间段: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}\n\n"
    )

    total_days = (end_date - start_date).days + 1
    days_with_data = len(filtered_df)
    data_summary += f"总天数: {total_days}, 有数据天数: {days_with_data}\n\n"

    if not filtered_df.empty:
        data_summary += "### 详细数据记录\n\n"

        for col in all_columns:
            has_data = filtered_df[col].notna().any()
            if has_data:
                col_title = col.replace("\n", " ")
                data_summary += f"#### {col_title}记录\n\n"

                col_data = filtered_df[["日期", col]].dropna(subset=[col])
                for _, row in col_data.iterrows():
                    value = row[col]
                    if col in ["体重", "体脂率"]:
                        data_summary += (
                            f"- {row['日期'].strftime('%Y-%m-%d')}: {value} "
                            f"{'kg' if col == '体重' else '%'}\n"
                        )
                    elif col == "HHH":
                        try:
                            # Handle string inputs that might have symbols like '+1'
                            if isinstance(value, str):
                                num_val = float(value)
                            else:
                                num_val = float(value)
                            
                            count = abs(num_val)
                            formatted_count = int(count) if count.is_integer() else count
                            
                            if num_val < 0:
                                display_val = f"手淫 {formatted_count}次"
                            elif num_val > 0:
                                display_val = f"性关系 {formatted_count}次"
                            else:
                                display_val = str(value)
                        except (ValueError, TypeError):
                            display_val = str(value)
                        
                        data_summary += f"- {row['日期'].strftime('%Y-%m-%d')}: {display_val}\n"
                    else:
                        data_summary += f"- {row['日期'].strftime('%Y-%m-%d')}: {value}\n"
                data_summary += "\n"
    else:
        data_summary += "在指定时间段内没有找到任何数据。\n\n"

    data_summary += "### 数据统计摘要\n\n"

    for col in all_columns:
        clean_col_name = col.replace("\n", " ")
        data_summary += f"- {clean_col_name}记录: {filtered_df[col].count()} 天\n"

    data_summary += "\n"

    for col in all_columns:
        latest_value = (
            filtered_df[col].dropna().iloc[-1] if filtered_df[col].dropna().any() else None
        )
        latest_date = filtered_df["日期"].max() if not filtered_df.empty else None

        if latest_value is not None:
            clean_col_name = col.replace("\n", " ")
            if col in ["体重", "体脂率"]:
                data_summary += (
                    f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                    f"{latest_value} {'kg' if col == '体重' else '%'}\n"
                )
            elif col == "HHH":
                try:
                    # Reuse logic or simplify for latest value
                    if isinstance(latest_value, str):
                         num_val = float(latest_value)
                    else:
                         num_val = float(latest_value)
                    
                    count = abs(num_val)
                    formatted_count = int(count) if count.is_integer() else count
                    
                    if num_val < 0:
                         display_val = f"手淫 {formatted_count}次"
                    elif num_val > 0:
                         display_val = f"性关系 {formatted_count}次"
                    else:
                         display_val = str(latest_value)
                except (ValueError, TypeError):
                    display_val = str(latest_value)

                data_summary += (
                    f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                    f"{display_val}\n"
                )
            else:
                data_summary += (
                    f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                    f"{latest_value}\n"
                )

    combined_content = f"{prompt_content}\n\n{data_summary}"

    if project_mgmt_path.exists():
        pm_content = project_mgmt_path.read_text(encoding="utf-8")
        combined_content += f"\n\n# Project Management Context\n\n{pm_content}"

    output_filename = f"combined_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output_path = get_history_dir(Path.cwd()) / output_filename
    output_path.write_text(combined_content, encoding="utf-8")

    print(f"已成功生成合并文件: {output_path}")

    return output_path


def build_payload(prompt_text, model):
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "stream": False,
        "max_tokens": 4096,
        "enable_thinking": False,
        "thinking_budget": 4096,
        "min_p": 0.05,
        "stop": None,
        "temperature": 0.7,
        "top_p": 0.7,
        "top_k": 50,
        "frequency_penalty": 0.5,
        "n": 1,
        "response_format": {"type": "text"},
    }


def call_model(prompt_text):
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.environ.get("SILICONFLOW_MODEL")
    api_key = os.environ.get("SILICONFLOW_API_KEY")

    if not model:
        raise ValueError("缺少环境变量 SILICONFLOW_MODEL")
    if not api_key:
        raise ValueError("缺少环境变量 SILICONFLOW_API_KEY")

    url = base_url.rstrip("/") + "/chat/completions"
    payload = build_payload(prompt_text, model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    return response.json()


def call_model_messages(messages):
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.environ.get("SILICONFLOW_MODEL")
    api_key = os.environ.get("SILICONFLOW_API_KEY")

    if not model:
        raise ValueError("缺少环境变量 SILICONFLOW_MODEL")
    if not api_key:
        raise ValueError("缺少环境变量 SILICONFLOW_API_KEY")

    url = base_url.rstrip("/") + "/chat/completions"
    
    # Construct payload manually to support messages list
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": 4096,
        "enable_thinking": False,
        "thinking_budget": 4096,
        "min_p": 0.05,
        "stop": None,
        "temperature": 0.7,
        "top_p": 0.7,
        "top_k": 50,
        "frequency_penalty": 0.5,
        "n": 1,
        "response_format": {"type": "text"},
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    start_time = time.time()
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    
    result = response.json()
    duration = time.time() - start_time
    result["_duration_seconds"] = duration
    
    return result


def extract_text(response_json):
    try:
        return response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def extract_usage(response_json):
    try:
        usage = response_json.get("usage", {})
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "duration": response_json.get("_duration_seconds", 0)
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "duration": 0}


def save_context(base_dir, messages):
    history_dir = get_history_dir(base_dir)
    context_file = history_dir / "latest_context.json"
    try:
        with open(context_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        print(f"Context saved to: {context_file}")
    except Exception as e:
        print(f"Warning: Failed to save context: {e}")
    return context_file

def load_context(context_file_path):
    path = Path(context_file_path)
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def transcribe_audio(file_path):
    base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    
    if not api_key:
        raise ValueError("缺少环境变量 SILICONFLOW_API_KEY")
        
    url = base_url.rstrip("/") + "/audio/transcriptions"
    
    # Model: fun-audio-llm/sensevoice-small is a common choice on SiliconFlow
    # Fallback/Default might vary, checking env or default
    model = "FunAudioLLM/SenseVoiceSmall" 
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, "audio/wav"),
                "model": (None, model)
            }
        # Note: requests sends multipart/form-data when files is present
            # We don't verify SSL cert if sometimes issues on win
            response = requests.post(url, headers=headers, files=files, timeout=60)
            
        if not response.ok:
            print(f"API Error details: {response.text}")
            
        response.raise_for_status()
        result = response.json()
        return result.get("text", "")
        
    except Exception as e:
        print(f"Transcription error: {e}")
        return None

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Run AI Prompts")
    parser.add_argument("prompt_file", nargs="?", help="Path to the prompt file")
    parser.add_argument("output_file", nargs="?", help="Path to the output file")
    parser.add_argument("--transcribe", help="Path to audio file to transcribe")
    parser.add_argument("--chat_message", help="User message for chat mode")
    parser.add_argument("--context_file", help="Path to load context from")
    
    args = parser.parse_args()

    base_dir = Path.cwd()
    load_env_file(base_dir / ".env")
    
    # === TRANSCRIPT MODE ===
    if args.transcribe:
        text = transcribe_audio(args.transcribe)
        if text:
            print(f"TRANSCRIPTION_RESULT:{text}")
        else:
            print("TRANSCRIPTION_RESULT:")
        return

    # Load historical stats
    historical_stats = load_stats(base_dir)
    current_session_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "turns": 0,
        "total_duration": 0
    }

    # === CHAT MODE ===
    if args.chat_message:
        print("Mode: Chat")
        
        # Load context
        current_messages = []
        if args.context_file:
            current_messages = load_context(args.context_file)
        
        # If no context loaded, checks for fallback or error? 
        # For now, if no context, we just start fresh with system prompt (though we might miss it if not passed)
        if not current_messages:
            # Try to load default system prompt logic if context is empty
             system_prompt_path = base_dir / "Prompt_System.md"
             if system_prompt_path.exists():
                sys_content = system_prompt_path.read_text(encoding="utf-8").strip()
                current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
                if "{current_time}" in sys_content:
                     sys_content = sys_content.replace("{current_time}", current_time_str)
                if "{当前时间}" in sys_content:
                     sys_content = sys_content.replace("{当前时间}", current_time_str)
                current_messages.append({"role": "system", "content": sys_content})

        # Append new user message
        current_messages.append({"role": "user", "content": args.chat_message})
        
        print("Thinking...")
        response_json = call_model_messages(current_messages)
        content = extract_text(response_json)
        
        # Stats update
        usage = extract_usage(response_json)
        current_session_usage["prompt_tokens"] += usage["prompt_tokens"]
        current_session_usage["completion_tokens"] += usage["completion_tokens"]
        current_session_usage["total_tokens"] += usage["total_tokens"]
        current_session_usage["turns"] += 1
        current_session_usage["total_duration"] += usage.get("duration", 0)
        
        historical_stats["total_prompt_tokens"] += usage["prompt_tokens"]
        historical_stats["total_completion_tokens"] += usage["completion_tokens"]
        historical_stats["total_conversations"] += 1
        
        if content:
            print(content) # Print to stdout for GUI to capture
            current_messages.append({"role": "assistant", "content": content})
            
            # Save updated context
            if args.context_file:
                 # Overwrite the context file
                 try:
                    with open(args.context_file, 'w', encoding='utf-8') as f:
                        json.dump(current_messages, f, ensure_ascii=False, indent=2)
                 except Exception as e:
                    print(f"Error saving context: {e}")
            else:
                # Save to default latest
                save_context(base_dir, current_messages)
        else:
            print("Error: No content returned.")

    # === NORMAL MODE ===
    else:
        # Compatibility with old positional args logic
        if args.prompt_file:
            prompt_path = Path(args.prompt_file)
        else:
            prompt_path = extract_recent_data_and_combine(
                resolve_data_path("Prompt_Personal_Info.md"),
                resolve_data_path("Time.xlsx"),
                days=30,
            )
            
        if args.output_file:
            output_path = Path(args.output_file)
        else:
            output_path = get_history_dir(base_dir) / f"model_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        prompt_text = prompt_path.read_text(encoding="utf-8")
        
        # Prepare messages
        current_messages = []
        
        # Check for System Prompt
        system_prompt_path = base_dir / "Prompt_System.md"
        system_prompt_content = ""
        
        if system_prompt_path.exists():
            system_prompt_content = system_prompt_path.read_text(encoding="utf-8").strip()
        
        # Inject current time context into system prompt
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        if system_prompt_content:
            # Support placeholder replacement
            if "{current_time}" in system_prompt_content:
                 system_prompt_content = system_prompt_content.replace("{current_time}", current_time_str)
            # Also support {当前时间} just in case
            if "{当前时间}" in system_prompt_content:
                 system_prompt_content = system_prompt_content.replace("{当前时间}", current_time_str)
        else:
            # Fallback system prompt if file not found
            system_prompt_content = f"Context: Current Date and Time is {current_time_str}."

        if system_prompt_content:
            current_messages.append({"role": "system", "content": system_prompt_content})
            print(f"已加载系统提示词 (System Prompt)")

        # Add User Prompt (without time context duplicate)
        current_messages.append({"role": "user", "content": prompt_text})
        
        print("正在生成初始分析报告，请稍候...")
        response_json = call_model_messages(current_messages)
        content = extract_text(response_json)
        
        # Update stats
        usage = extract_usage(response_json)
        current_session_usage["prompt_tokens"] += usage["prompt_tokens"]
        current_session_usage["completion_tokens"] += usage["completion_tokens"]
        current_session_usage["total_tokens"] += usage["total_tokens"]
        current_session_usage["turns"] += 1
        current_session_usage["total_duration"] += usage.get("duration", 0)
        
        historical_stats["total_prompt_tokens"] += usage["prompt_tokens"]
        historical_stats["total_completion_tokens"] += usage["completion_tokens"]
        historical_stats["total_conversations"] += 1
        current_session_usage["total_duration"] += usage.get("duration", 0)

        if content is None:
            output_path.write_text(str(response_json), encoding="utf-8")
            print("Error: Failed to get response content.")
            return
        else:
            output_path.write_text(content, encoding="utf-8")
            # Add assistant response to history
            current_messages.append({"role": "assistant", "content": content})

        # Save stats and generate report
        save_stats(base_dir, historical_stats)
        generate_usage_report(
            base_dir, 
            current_session_usage, 
            historical_stats, 
            os.environ.get("SILICONFLOW_MODEL", "Unknown")
        )

        print("---ANALYSIS_START---")
        print(content)
        print("初始分析已完成。正在生成今日行动建议...")
        
        # Second pass: Generate Today's Action Plan
        current_time_dt = datetime.now()
        current_time = current_time_dt.strftime('%Y-%m-%d %H:%M')
        
        # Try to load today's data from Excel
        today_data_str = "Today's Excel Data: None found."
        try:
            excel_path = resolve_data_path("Time.xlsx")
            if excel_path.exists():
                df_full = load_excel_data(excel_path)
                # Normalize dates for comparison
                df_full['DateOnly'] = df_full['日期'].dt.date
                today_date_obj = current_time_dt.date()
                
                today_row = df_full[df_full['DateOnly'] == today_date_obj]
                
                if not today_row.empty:
                    # Convert the single row to a readable string
                    row_dict = today_row.iloc[0].to_dict()
                    parts = []
                    for k, v in row_dict.items():
                        if k in ['日期', 'DateOnly']: continue
                        if pd.isna(v): continue
                        parts.append(f"{k}: {v}")
                    
                    if parts:
                        today_data_str = "Today's Excel Data:\n" + "\n".join([f"- {p}" for p in parts])
        except Exception as e:
            print(f"Warning: Failed to load today's Excel data: {e}")

        # Load action plan prompt from file
        action_plan_prompt_path = base_dir / "Prompt_Action_Plan.md"
        if action_plan_prompt_path.exists():
            action_plan_prompt = action_plan_prompt_path.read_text(encoding="utf-8")
            
            # Inject today's data row
            if "{today_data_row}" in action_plan_prompt:
                 action_plan_prompt = action_plan_prompt.replace("{today_data_row}", today_data_str)
            else:
                 # Auto-append if placeholder missing
                 action_plan_prompt += f"\n\n{today_data_str}"

            # Replace {current_time} placeholder
            action_plan_prompt = action_plan_prompt.replace("{current_time}", current_time)
            action_plan_prompt = action_plan_prompt.replace("{当前时间}", current_time)
            # Backward compatibility in case usage varies
            action_plan_prompt = action_plan_prompt.replace("{today_date}", current_time.split()[0])
        else:
            # Fallback to default if file doesn't exist
            action_plan_prompt = f"""
基于上述分析，请为我生成今天的行动建议（Today's Action Plan）。
现在是 {current_time}。
{today_data_str}
请输出一个独立的 Markdown 文档，只包含今天需要做的事情。
格式要求：
1. 核心任务（P0/P1）
2. 具体行动（时间点+事项）
3. 注意事项
"""
        current_messages.append({"role": "user", "content": action_plan_prompt})
        
        response_json = call_model_messages(current_messages)
        action_plan_content = extract_text(response_json)
        
        # Update stats for second pass
        usage = extract_usage(response_json)
        current_session_usage["prompt_tokens"] += usage["prompt_tokens"]
        current_session_usage["completion_tokens"] += usage["completion_tokens"]
        current_session_usage["total_tokens"] += usage["total_tokens"]
        current_session_usage["turns"] += 1
        current_session_usage["total_duration"] += usage.get("duration", 0)
        
        historical_stats["total_prompt_tokens"] += usage["prompt_tokens"]
        historical_stats["total_completion_tokens"] += usage["completion_tokens"]
        historical_stats["total_conversations"] += 1
        
        if action_plan_content:
            action_plan_filename = f"action_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            action_plan_path = get_history_dir(base_dir) / action_plan_filename
            action_plan_path.write_text(action_plan_content, encoding="utf-8")
            current_messages.append({"role": "assistant", "content": action_plan_content})
            print(f"已生成今日行动建议: {action_plan_path}")
        else:
            print("Error: Failed to generate action plan.")
            
        # SAVE CONTEXT FOR CHAT
        save_context(base_dir, current_messages)

    # Save stats and generate report (Final update)
    save_stats(base_dir, historical_stats)
    report_path = generate_usage_report(
        base_dir, 
        current_session_usage, 
        historical_stats, 
        os.environ.get("SILICONFLOW_MODEL", "Unknown")
    )
    
    print(f"已更新统计报告: {report_path}")
    
    # Print Summary to Terminal
    print("\n" + "="*30)
    print("       本次会话统计")
    print("="*30)
    print(f"对话轮数: {current_session_usage['turns']}")
    print(f"本次消耗 Tokens: {current_session_usage['total_tokens']}")
    print(f"  - Prompt: {current_session_usage['prompt_tokens']}")
    print(f"  - Completion: {current_session_usage['completion_tokens']}")
    print("-" * 30)
    print(f"历史总消耗 Tokens: {historical_stats['total_prompt_tokens'] + historical_stats['total_completion_tokens']}")
    print("="*30 + "\n")
    
    # Print JSON for GUI to parse
    # Calculate average speed
    total_duration = current_session_usage.get("total_duration", 0) # We need to accumulate this
    total_tokens = current_session_usage["total_tokens"]
    # Calculate speed based on completion tokens only (Generation Speed)
    completion_tokens = current_session_usage["completion_tokens"]
    speed = completion_tokens / total_duration if total_duration > 0 else 0
    
    stats_output = {
        "turns": current_session_usage['turns'],
        "prompt_tokens": current_session_usage['prompt_tokens'],
        "completion_tokens": current_session_usage['completion_tokens'],
        "total_tokens": total_tokens,
        "total_duration": total_duration,
        "speed": f"{speed:.2f} tokens/s"
    }
    print(f"STATS_JSON:{json.dumps(stats_output)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
