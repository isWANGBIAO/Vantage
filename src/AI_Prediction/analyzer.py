import pandas as pd
import numpy as np
import re
import jieba
import os
import json
from tqdm import tqdm
from openai import OpenAI  # 阿里云兼容openai sdk
from src.utils.data_loader import DataLoader
from src.services.tracked_openai_client import TrackedOpenAIClient


def _build_tracked_client(client, base_url):
    return TrackedOpenAIClient(
        client=client,
        source="ai_prediction",
        entrypoint="src/AI_Prediction/analyzer.py",
        base_url=base_url,
    )


def llm_classify(text):
    """
    用大模型API对text进行分词和分类，返回结构如：
    {
        "食物": ["牛肉", "米饭"],
        "餐厅": ["肯德基"],
        "活动": ["聚会"]
    }
    """
    api_key = os.getenv('ALIYUN_ACCESS_KEY')
    url = os.getenv('ALIYUN_ACCESS_BASE_URL')
    golbal_model = 'qwen-max-latest'
    if not api_key or not url:
        raise ValueError("请设置环境变量 ALIYUN_ACCESS_KEY 和 ALIYUN_ACCESS_BASE_URL")
    client = OpenAI(base_url=url, api_key=api_key)
    tracked_client = _build_tracked_client(client, url)
    prompt = (
        f"请将下列文本分词并按如下JSON格式分类：'食物'、'餐厅'、'活动'，只返回JSON，不要多余解释。\n"
        f"文本：{text}\n"
        "输出示例：{\"食物\":[...],\"餐厅\":[...],\"活动\":[...]}"
    )
    try:
        # 实时显示进度
        print(f"正在分析: {text[:]}", flush=True)
        completion = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.2
        )
        reply = completion.choices[0].message.content.strip()
        # 尝试提取JSON
        match = re.search(r'\{[\s\S]*\}', reply)
        if match:
            reply = match.group(0)
        result = json.loads(reply)
        # 确保有三个key
        for k in ["食物", "餐厅", "活动"]:
            if k not in result:
                result[k] = []
        return result
    except Exception as e:
        print(f"llm_classify调用失败: {e}")
        return {"食物": [], "餐厅": [], "活动": []}


def llm_extract_meals(text):
    """
    用大模型API对饮食描述进行餐次结构化，返回如：
    {
        "早餐": ["鸡蛋", "牛奶"],
        "午餐": ["米饭", "红烧肉"],
        "晚餐": ["面条"],
        "小吃": ["薯片"]
    }
    """
    api_key = os.getenv('ALIYUN_ACCESS_KEY')
    url = os.getenv('ALIYUN_ACCESS_BASE_URL')
    golbal_model = 'qwen-max-latest'
    if not api_key or not url:
        raise ValueError("请设置环境变量 ALIYUN_ACCESS_KEY 和 ALIYUN_ACCESS_BASE_URL")
    client = OpenAI(base_url=url, api_key=api_key)
    tracked_client = _build_tracked_client(client, url)
    prompt = (
        f"请将下列饮食描述按餐次结构化，输出JSON，key为餐次（早餐、午餐、晚餐、小吃），value为食物列表，只返回JSON：\n{text}\n"
        "示例：{\"早餐\":[...],\"午餐\":[...],\"晚餐\":[...],\"小吃\":[...]}")
    try:
        completion = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2
        )
        reply = completion.choices[0].message.content.strip()
        match = re.search(r'\{[\s\S]*\}', reply)
        if match:
            reply = match.group(0)
        result = json.loads(reply)
        for k in ["早餐", "午餐", "晚餐", "小吃"]:
            if k not in result:
                result[k] = []
        return result
    except Exception as e:
        print(f"llm_extract_meals调用失败: {e}")
        return {"早餐": [], "午餐": [], "晚餐": [], "小吃": []}


def llm_extract_diarrhea_info(text):
    """
    用大模型API对健康描述提取拉稀次数、严重程度、时间，返回如：
    [
      {"次数": 1, "程度": "轻微", "时间": "早上"},
      {"次数": 2, "程度": "严重", "时间": "下午"}
    ]
    """
    api_key = os.getenv('ALIYUN_ACCESS_KEY')
    url = os.getenv('ALIYUN_ACCESS_BASE_URL')
    golbal_model = 'qwen-max-latest'
    if not api_key or not url:
        raise ValueError("请设置环境变量 ALIYUN_ACCESS_KEY 和 ALIYUN_ACCESS_BASE_URL")
    client = OpenAI(base_url=url, api_key=api_key)
    tracked_client = _build_tracked_client(client, url)
    prompt = (
        f"请从下列健康描述中提取所有拉稀事件，输出JSON数组，每个元素包含次数、严重程度（如轻微/中等/严重）、时间（如早上/下午/晚上/凌晨），只返回JSON：\n{text}\n"
        "示例：[{'次数':1,'程度':'轻微','时间':'早上'}]"
    )
    try:
        completion = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2
        )
        reply = completion.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', reply, re.DOTALL)
        if match:
            reply = match.group(0)
        # 修正单引号为双引号，兼容大模型输出
        reply = reply.replace("'", '"')
        result = json.loads(reply)
        if not isinstance(result, list):
            result = []
        return result
    except Exception as e:
        print(f"llm_extract_diarrhea_info调用失败: {e}")
        return []


def read_and_preprocess_data():
    time_sheet_path = DataLoader.resolve_data_path("Time.xlsx")
    df = pd.read_excel(time_sheet_path)
    # 只保留日期、饮食和健康情况三列
    eat_col = '生活（饮食+社交+运动）'
    health_col = '健康情况'
    date_col = '日期'
    df = df[[date_col, eat_col, health_col]]

    # 找到健康情况有数据的行的索引
    valid_idx = df[df[health_col].notna() & (df[health_col] != '')].index.tolist()
    # 保留这些行和它们的上一行（如果存在）
    keep_idx = set(valid_idx)
    for idx in valid_idx:
        if idx > 0:
            keep_idx.add(idx - 1)
    keep_idx = sorted(keep_idx)
    df_valid = df.loc[keep_idx].reset_index(drop=True)

    output_dir = os.path.dirname('src/AI_Prediction/data/有效数据表.csv')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    df_valid.to_csv('src/AI_Prediction/data/有效数据表.csv', index=False, encoding='utf-8-sig')
    return df_valid


def analyze_food_and_restaurant(df):
    eat_col = '生活（饮食+社交+运动）'
    health_col = '健康情况'
    date_col = '日期'

    def extract_food_and_restaurant(s):
        if not isinstance(s, str) or not s.strip():
            return []
        result = llm_classify(s)
        print(f"模型结果: {result}")
        return (result.get("食物", []) or []) + (result.get("餐厅", []) or [])

    def extract_diarrhea_count(s):
        if not isinstance(s, str) or not s.strip():
            return 0
        events = llm_extract_diarrhea_info(s)
        print(f"模型结果: {events}")
        return sum(e.get("次数", 0) for e in events if isinstance(e, dict) and "次数" in e)

    analysis_path = 'src/AI_Prediction/data/大模型分析表.csv'
    if (os.path.exists(analysis_path)):
        print(f"检测到表 {analysis_path}，直接读取...")
        df_analysis = pd.read_csv(analysis_path, encoding='utf-8-sig')
    else:
        df = df.copy()
        df['食物餐厅'] = df[eat_col].map(extract_food_and_restaurant)
        df['拉稀次数'] = df[health_col].map(extract_diarrhea_count)
        # explode前先保存拉稀次数
        df_expanded = df.explode('食物餐厅').reset_index(drop=True)
        # 拉稀次数列需要重复填充到每一行
        df_expanded['拉稀次数'] = df_expanded['拉稀次数'].astype(int)
        df_analysis = df_expanded[df_expanded['食物餐厅'].notna() & (df_expanded['食物餐厅'] != '')]
        keep_cols_analysis = [date_col, eat_col, health_col, '食物餐厅', '拉稀次数']
        df_analysis = df_analysis[keep_cols_analysis].copy()
        df_analysis.to_csv(analysis_path, index=False, encoding='utf-8-sig')
        print(f"已生成表 {analysis_path}")
    return df_analysis


def statistical_analysis(df):
    # 确保拉稀次数为整数类型
    if '拉稀次数' in df.columns:
        df['拉稀次数'] = pd.to_numeric(df['拉稀次数'], errors='coerce').fillna(0).astype(int)

    # 计算“次日拉稀次数”列，保证日期是相邻的
    df = df.sort_values('日期').reset_index(drop=True)
    # 计算日期差（天数）
    df['日期_diff'] = pd.to_datetime(df['日期']).shift(-1) - pd.to_datetime(df['日期'])
    # 仅当日期差为1天时才赋值，否则为0
    next_diarrhea = df['拉稀次数'].shift(-1)
    df['次日拉稀次数'] = 0
    mask = df['日期_diff'].dt.days == 1
    df.loc[mask, '次日拉稀次数'] = pd.Series(next_diarrhea)[mask].fillna(0).astype(int)
    # 计算“当日及次日拉稀次数”
    df['当日及次日拉稀次数'] = df['拉稀次数'] + df['次日拉稀次数']
    df = df.drop(columns=['日期_diff'])
    stats = df.groupby('食物餐厅').agg(
        总出现次数=('食物餐厅', 'size'),
        拉稀次数=('拉稀次数', 'sum'),
        当日及次日拉稀次数=('当日及次日拉稀次数', 'sum')
    )
    stats['拉稀率'] = (stats['拉稀次数'] / stats['总出现次数']).map("{:.2%}".format)
    stats['当日及次日拉稀率'] = (stats['当日及次日拉稀次数'] / stats['总出现次数']).map("{:.2%}".format)
    result = (
        stats.assign(_rate=stats['拉稀率'].str.rstrip('%').astype(float))
        .sort_values(['总出现次数', '_rate'], ascending=[False, False])
        .drop(columns=['_rate'])
        .reset_index()
    )
    result.to_csv('src/AI_Prediction/data/食物过敏分析表.csv', index=False, encoding='utf-8-sig')
    return result


def main():
    df_valid = read_and_preprocess_data()
    df_analysis = analyze_food_and_restaurant(df_valid)
    statistical_analysis(df_analysis)


if __name__ == '__main__':
    main()
