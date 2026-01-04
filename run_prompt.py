import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests


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
            os.environ[key] = value.strip()


def get_history_dir(base_dir):
    history_dir = base_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir


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


def extract_recent_data_and_combine(prompt_file_path, excel_file_path, days=30):
    prompt_file_path = Path(prompt_file_path)
    excel_file_path = Path(excel_file_path)

    if not prompt_file_path.exists():
        raise FileNotFoundError(f"未找到 Prompt 文件: {prompt_file_path}")
    if not excel_file_path.exists():
        raise FileNotFoundError(f"未找到 Excel 文件: {excel_file_path}")

    prompt_content = prompt_file_path.read_text(encoding="utf-8")

    df = pd.read_excel(excel_file_path, engine="openpyxl")
    if "日期" not in df.columns:
        raise KeyError(f"Excel中缺少'日期'列: {excel_file_path}")
    df["日期"] = pd.to_datetime(df["日期"])

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
            else:
                data_summary += (
                    f"- 最新{clean_col_name}记录: {latest_date.strftime('%Y-%m-%d')}, "
                    f"{latest_value}\n"
                )

    combined_content = f"{prompt_content}\n\n{data_summary}"

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


def extract_text(response_json):
    try:
        return response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def main():
    base_dir = Path.cwd()
    load_env_file(base_dir / ".env")

    if len(sys.argv) > 1:
        prompt_path = Path(sys.argv[1])
    else:
        prompt_path = extract_recent_data_and_combine(
            resolve_data_path("Prompt.md"),
            resolve_data_path("Time.xlsx"),
            days=30,
        )
    output_path = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else get_history_dir(base_dir)
        / f"model_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )

    prompt_text = prompt_path.read_text(encoding="utf-8")
    response_json = call_model(prompt_text)
    content = extract_text(response_json)

    if content is None:
        output_path.write_text(str(response_json), encoding="utf-8")
    else:
        output_path.write_text(content, encoding="utf-8")

    print(f"已生成模型结果: {output_path}")


if __name__ == "__main__":
    main()
