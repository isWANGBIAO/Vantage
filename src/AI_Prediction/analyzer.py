import pandas as pd
import numpy as np
import re
import os

# --- 配置 ---
# 确定当前脚本的目录
script_dir = os.path.dirname(__file__)
# 构建相对于脚本目录的数据文件的绝对路径
DATA_PATH = os.path.join(script_dir, 'data/Time.csv')

# --- 数据加载和预处理


def parse_sleep_time(time_str):
    """将睡眠时长字符串 'X小时Y分' 转换为总小时数。"""
    if pd.isna(time_str) or time_str == '':
        return np.nan
    hours = 0
    minutes = 0
    hour_match = re.search(r'(\\d+)\\s*小时', str(time_str))
    minute_match = re.search(r'(\\d+)\\s*分', str(time_str))
    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    return hours + minutes / 60.0


def load_and_preprocess_data(file_path):
    """从 CSV 加载并预处理健康数据。"""
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(file_path, encoding='gbk')
        except Exception as e:
            print(f"Error reading CSV with multiple encodings: {e}")
            return None
    except FileNotFoundError:
        print(f"Error: Data file not found at {file_path}")
        return None

    print("原始列名:", df.columns.tolist())
    df.columns = [col.replace('\\r\\n', '').replace('\\n', '') for col in df.columns]
    print("清理后的列名:", df.columns.tolist())

    relevant_cols = {
        '日期': 'Date',
        '健康情况': 'HealthNotes',
        '生活（饮食+社交+运动）': 'LifeNotes'
    }
    existing_cols = {k: v for k, v in relevant_cols.items() if k in df.columns}
    # 特别检查分析器所需的列
    required_analyzer_cols = ['Date', 'HealthNotes', 'LifeNotes']
    if not all(col in existing_cols.values() for col in required_analyzer_cols):
        missing = [col for col in required_analyzer_cols if col not in existing_cols.values()]
        print(f"错误: 重命名后未找到分析所需的列 ({', '.join(missing)})。")
        # 如果重命名失败，尝试查找原始名称
        original_missing = []
        reverse_map = {v: k for k, v in relevant_cols.items()}
        for col in missing:
            original_name = reverse_map.get(col)
            if original_name and original_name not in df.columns:
                original_missing.append(original_name)
            elif not original_name:
                original_missing.append(f"(未知 {col} 的原始名称)")

        if original_missing:
            print(f"CSV 中缺少原始必需列: {', '.join(original_missing)}")
        return None

    df = df[[k for k, v in relevant_cols.items() if k in df.columns]]
    df = df.rename(columns=existing_cols)

    if 'Date' not in df.columns:
        print("Error: '日期' (Date) column is missing.")
        return None
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.dropna(subset=['Date'])
    df = df.sort_values('Date').reset_index(drop=True)

    # 填充缺失的文本数据 - 对分析器很重要
    text_cols = ['HealthNotes', 'LifeNotes']
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].fillna('')
        else:
            print(f"警告: 列 {col} 预期存在但未找到，将创建空列。")
            df[col] = ''

    print("处理后的数据头部 (供分析器使用):")
    print(df.head())
    print("数据信息 (供分析器使用):")
    df.info()

    return df


# --- 过敏分析函数 (恢复为关联性分析) ---
def analyze_allergies(df):
    """分析健康笔记和生活笔记之间的潜在关联，找出可能与'拉'相关的词语。"""
    print("--- 分析潜在触发因素 (基于 LifeNotes 与 HealthNotes 关联) ---")

    if 'HealthNotes' not in df.columns or 'LifeNotes' not in df.columns:
        print("错误: 未找到 'HealthNotes' 或 'LifeNotes' 列。无法执行分析。")
        return

    # 定义健康问题关键词
    issue_keywords = ['拉', '肚子', '泻', '喷射']
    try:
        df['HealthNotes'] = df['HealthNotes'].astype(str)  # 确保是字符串类型
        # 找到包含问题关键词的行 (问题日)
        issue_days = df[df['HealthNotes'].str.contains('|'.join(issue_keywords), na=False, regex=True)]
    except Exception as e:
        print(f"搜索问题关键词期间出错: {e}")
        issue_days = pd.DataFrame()

    if issue_days.empty:
        print("在 'HealthNotes' 中未找到特定的健康问题关键词。无法执行分析。")
        return

    num_issue_days = len(issue_days)
    print(f"在 HealthNotes 中找到 {num_issue_days} 天提及潜在的消化问题。")

    potential_triggers = {}

    # 定义要排除的常见非食物词/名称/地点 (可以根据需要扩展)
    stop_words = set([
        ' ', '的', '了', '和', '是', '在', '我', '有', '也', '不', '都', '就',
        '很', '点', '个', '还', '吃', '喝', '玩', '去', '回', '家', '公司',
        '上班', '下班', '中午', '晚上', '早上', '下午', '昨天', '今天', '明天',
        # 可以添加更多地点、人名、常见活动等
        '外卖', '食堂', '自己做', '一点', '有点'  # 示例
    ])

    # 遍历每个问题日
    for index, row in issue_days.iterrows():
        current_date = row['Date']
        relevant_notes_list = []

        # 获取前一天的 LifeNotes
        # 需要找到排序后 DataFrame 中当前行的位置，然后获取前一行的索引
        current_loc = df.index.get_loc(index)
        if current_loc > 0:
            prev_row_index = df.index[current_loc - 1]
            # 检查前一天的日期是否确实是连续的前一天 (可选)
            # if df.loc[prev_row_index, 'Date'] == current_date - pd.Timedelta(days=1):
            prev_day_notes = df.loc[prev_row_index, 'LifeNotes']
            if pd.notna(prev_day_notes):
                relevant_notes_list.append(str(prev_day_notes))

        # 获取当天的 LifeNotes
        current_day_notes = row['LifeNotes']
        if pd.notna(current_day_notes):
            relevant_notes_list.append(str(current_day_notes))

        # 合并前一天和当天的笔记文本
        relevant_notes_text = " | ".join(relevant_notes_list)

        # 使用正则表达式分割词语 (更精细的分隔符)
        potential_items = re.split(r'[\s、，；。？！｜|(),./:;"\'\\\\[\\]\\{\\}<>+-=\\*&^%$#@!`~\\d]+', relevant_notes_text)

        # 统计每个词的出现次数
        for item in potential_items:
            item_cleaned = item.strip()
            # 过滤掉空字符串、单个字符、纯数字和停用词
            if len(item_cleaned) > 1 and not item_cleaned.isnumeric() and item_cleaned not in stop_words:
                potential_triggers[item_cleaned] = potential_triggers.get(item_cleaned, 0) + 1

    # 计算可能性得分
    possibility_table = {}
    if num_issue_days > 0:
        for item, count in potential_triggers.items():
            # 得分 = (在问题日及前一日 LifeNotes 中出现的总次数) / (总问题天数)
            score = count / num_issue_days
            # 可以设置阈值过滤低频词，例如至少出现2次或得分大于某个值
            # if count >= 2: # or score > 0.1:
            possibility_table[item] = score

    print("--- 可能性表 (Potential Trigger Possibility Table) ---")
    print("分析 'HealthNotes' 中出现 '拉' 等关键词的当天及前一天的 'LifeNotes'。")
    print(f"总问题天数: {num_issue_days}")
    print("可能性 = (该词语在问题期间 LifeNotes 中出现的总次数) / (总问题天数)")
    print("-" * 60)
    print(f"{'Potential Item':<20} | {'Count':<5} | {'Possibility':<10}")
    print("-" * 60)

    if possibility_table:
        # 按可能性得分排序 (降序)
        sorted_table = sorted(possibility_table.items(), key=lambda item: item[1], reverse=True)
        for item, score in sorted_table:
            count = potential_triggers[item]  # 获取原始计数
            print(f"{item:<20} | {count:<5} | {score:<10.2f}")
    else:
        print("未能提取足够信息生成可能性表。")

    print("-" * 60)
    print("免责声明：此分析基于词语共现频率，并非医学诊断。")
    print("结果可能包含巧合或非直接原因。请结合实际情况判断。")


# --- 主执行 ---
if __name__ == "__main__":
    print("加载数据并分析可能的过敏原...")
    df_health = load_and_preprocess_data(DATA_PATH)

    if df_health is not None and not df_health.empty:
        analyze_allergies(df_health)
    elif df_health is None:
        print("数据加载失败或文件不存在。请检查文件路径和格式。")
    else:  # df_health 不为 None 但为空
        print("数据文件为空或没有有效数据。请检查数据源。")
