import pandas as pd
import numpy as np
import re
import jieba
import os
import json
from tqdm import tqdm
from openai import OpenAI  # 阿里云兼容openai sdk


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
    prompt = (
        f"请将下列文本分词并按如下JSON格式分类：'食物'、'餐厅'、'活动'，只返回JSON，不要多余解释。\n"
        f"文本：{text}\n"
        "输出示例：{\"食物\":[...],\"餐厅\":[...],\"活动\":[...]}"
    )
    try:
        # 实时显示进度
        print(f"正在分析: {text[:]}", flush=True)
        completion = client.chat.completions.create(
            model=golbal_model,
            messages=[
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=512,
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
    prompt = (
        f"请将下列饮食描述按餐次结构化，输出JSON，key为餐次（早餐、午餐、晚餐、小吃），value为食物列表，只返回JSON：\n{text}\n"
        "示例：{\"早餐\":[...],\"午餐\":[...],\"晚餐\":[...],\"小吃\":[...]}")
    try:
        completion = client.chat.completions.create(
            model=golbal_model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=512,
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
    prompt = (
        f"请从下列健康描述中提取所有拉稀事件，输出JSON数组，每个元素包含次数、严重程度（如轻微/中等/严重）、时间（如早上/下午/晚上/凌晨），只返回JSON：\n{text}\n"
        "示例：[{'次数':1,'程度':'轻微','时间':'早上'}]"
    )
    try:
        completion = client.chat.completions.create(
            model=golbal_model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=512,
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
    df = pd.read_excel(r'C:\Users\97012\OneDrive\Mine\Time.xlsx')
    eat_col = '生活（饮食+社交+运动）'
    health_col = '健康情况'
    date_col = '日期'
    p_good = re.compile(r'拉得好')
    p_bad = re.compile(r'拉了|拉稀|稀')
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)
    df['today_health'] = df[health_col]
    df['next_health'] = df[health_col].shift(-1)
    df['next_date'] = df[date_col].shift(-1)

    def diarrhea_flag(row):
        # 判断健康情况文本是否为“拉稀”或“正常”
        def is_diarrhea(x, p_good, p_bad):
            if pd.isna(x):
                return np.nan  # 如果是空值，返回NaN
            s = str(x)
            if p_good.search(s):
                return 0      # 如果匹配到“拉得好”，返回0（正常）
            return 1 if p_bad.search(s) else np.nan  # 匹配到“拉了/拉稀/稀”返回1，否则NaN
        today = is_diarrhea(row['today_health'], p_good, p_bad)
        if pd.notna(row['next_date']) and (row['next_date'] - row[date_col]).days == 1:
            nextd = is_diarrhea(row['next_health'], p_good, p_bad)
        else:
            nextd = np.nan
        if today == 1 or nextd == 1:
            return 1
        elif today == 0 and (np.isnan(nextd) or nextd == 0):
            return 0
        elif np.isnan(today) and (np.isnan(nextd) or nextd == 0):
            return 0
        else:
            return np.nan
    df['diarrhea'] = df.apply(diarrhea_flag, axis=1)

    df = df.dropna(subset=[eat_col, 'diarrhea'])
    df = df[~(df['today_health'].isna() & df['next_health'].isna())]
    keep_cols = [date_col, eat_col, health_col, 'today_health', 'next_health', 'next_date', 'diarrhea']
    df_valid = df[keep_cols].copy()
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
    analysis_path = f'src/AI_Prediction/data/大模型分析表.csv'
    if os.path.exists(analysis_path):
        print(f"检测到表 {analysis_path}，直接读取...")
        df = pd.read_csv(analysis_path, encoding='utf-8-sig')
    else:
        df['words'] = df[eat_col].map(extract_food_and_restaurant)
        df = df.explode('words')
        df = df[df['words'].notna() & (df['words'] != '')]
        keep_cols_analysis = [date_col, eat_col, health_col, 'today_health', 'next_health', 'next_date', 'diarrhea', 'words']
        df_analysis = df[keep_cols_analysis].copy()
        df_analysis.to_csv(analysis_path, index=False, encoding='utf-8-sig')
        print(f"已生成表 {analysis_path}")
    return df


def structure_meals_and_health(df_valid):
    eat_col = '生活（饮食+社交+运动）'
    health_col = '健康情况'
    date_col = '日期'
    print("正在结构化餐次和健康描述...")
    meal_cols = ["早餐", "午餐", "晚餐", "小吃"]
    meal_records = []
    # 检查明细表是否已存在，存在则直接读取
    detail_path = 'src/AI_Prediction/data/餐次食物拉稀明细表.csv'
    if os.path.exists(detail_path):
        print(f"检测到明细表 {detail_path}，直接读取...")
        meal_df = pd.read_csv(detail_path, encoding='utf-8-sig')
        # 统计分析
        stat = meal_df.groupby(['餐次', '食物']).agg(
            总出现次数=('食物', 'size'),
            拉稀天数=('拉稀次数', lambda x: pd.notna(x).sum()),
            拉稀总次数=('拉稀次数', 'sum'),
            严重天数=('拉稀程度', lambda x: (x == '严重').sum()),
            轻微天数=('拉稀程度', lambda x: (x == '轻微').sum()),
        ).reset_index()
        stat['拉稀率'] = (stat['拉稀天数'] / stat['总出现次数']).map('{:.2%}'.format)
        stat = stat.sort_values(['总出现次数', '拉稀天数'], ascending=[False, False])
        stat.to_csv('src/AI_Prediction/data/餐次食物拉稀统计表.csv', index=False, encoding='utf-8-sig')
        print('已保存餐次-食物-拉稀统计表')
        return meal_df, stat
    for idx, row in df_valid.iterrows():
        date = row[date_col]
        meal_dict = llm_extract_meals(str(row[eat_col]))
        diarrhea_events = llm_extract_diarrhea_info(str(row[health_col]))
        for meal in meal_cols:
            for food in meal_dict.get(meal, []):
                meal_records.append({
                    "日期": date,
                    "餐次": meal,
                    "食物": food,
                    "健康描述": row[health_col],
                    "拉稀事件": diarrhea_events
                })
        print(f"第{idx + 1}行分析完成，日期：{date}")
    meal_df = pd.DataFrame(meal_records)
    meal_df = meal_df.explode('拉稀事件').reset_index(drop=True)
    if not meal_df.empty:
        meal_df['拉稀次数'] = meal_df['拉稀事件'].apply(lambda x: x.get('次数') if isinstance(x, dict) else None)
        meal_df['拉稀程度'] = meal_df['拉稀事件'].apply(lambda x: x.get('程度') if isinstance(x, dict) else None)
        meal_df['拉稀时间'] = meal_df['拉稀事件'].apply(lambda x: x.get('时间') if isinstance(x, dict) else None)
    meal_df.to_csv('src/AI_Prediction/data/餐次食物拉稀明细表.csv', index=False, encoding='utf-8-sig')
    print('已保存餐次-食物-拉稀明细表')
    stat = meal_df.groupby(['餐次', '食物']).agg(
        总出现次数=('食物', 'size'),
        拉稀天数=('拉稀次数', lambda x: x.notna().sum()),
        拉稀总次数=('拉稀次数', 'sum'),
        严重天数=('拉稀程度', lambda x: (x == '严重').sum()),
        轻微天数=('拉稀程度', lambda x: (x == '轻微').sum()),
    ).reset_index()
    stat['拉稀率'] = (stat['拉稀天数'] / stat['总出现次数']).map('{:.2%}'.format)
    stat = stat.sort_values(['总出现次数', '拉稀天数'], ascending=[False, False])
    stat.to_csv('src/AI_Prediction/data/餐次食物拉稀统计表.csv', index=False, encoding='utf-8-sig')
    print('已保存餐次-食物-拉稀统计表')
    return meal_df, stat


def statistical_analysis(df):
    stats = df.groupby('words').agg(
        总出现次数=('words', 'size'),
        拉稀次数=('diarrhea', 'sum')
    )
    stats['拉稀率'] = (stats['拉稀次数'] / stats['总出现次数']).map("{:.2%}".format)
    result = (
        stats.assign(_rate=stats['拉稀率'].str.rstrip('%').astype(float))
        .sort_values(['总出现次数', '_rate'], ascending=[False, False])
        .drop(columns=['_rate'])
        .reset_index()
        .rename(columns={'words': '食物关键词'})
    )
    result.to_csv('src/AI_Prediction/data/食物过敏分析表.csv', index=False, encoding='utf-8-sig')
    return result


def main():
    df_valid = read_and_preprocess_data()
    df_analysis = analyze_food_and_restaurant(df_valid)
    statistical_analysis(df_analysis)
    structure_meals_and_health(df_valid)


if __name__ == '__main__':
    main()
