import pandas as pd
import numpy as np
import re
import jieba
import os
import json
from tqdm import tqdm
from openai import OpenAI  # 阿里云兼容openai sdk

# 判断健康情况文本是否为“拉稀”或“正常”


def is_diarrhea(x, p_good, p_bad):
    if pd.isna(x):
        return np.nan  # 如果是空值，返回NaN
    s = str(x)
    if p_good.search(s):
        return 0      # 如果匹配到“拉得好”，返回0（正常）
    return 1 if p_bad.search(s) else np.nan  # 匹配到“拉了/拉稀/稀”返回1，否则NaN


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


def main():
    # 1. 读数据
    # 从csv文件读取数据，假设有“日期”、“生活（饮食+社交+运动）”、“健康情况”三列
    df = pd.read_excel(r'C:\Users\97012\OneDrive\Mine\Time.xlsx')
    eat_col = '生活（饮食+社交+运动）'
    health_col = '健康情况'
    date_col = '日期'  # 日期列

    # 2. 预编译正则
    # p_good匹配“拉得好”，p_bad匹配“拉了/拉稀/稀”，valid用于分词后筛选有效词
    p_good = re.compile(r'拉得好')
    p_bad = re.compile(r'拉了|拉稀|稀')
    valid = re.compile(r'[\u4e00-\u9fa5A-Za-z0-9]')

    # 3. 日期处理，按日期排序
    # 将日期列转为datetime类型，并按日期升序排列
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    # 4. 生成 today_health 和 next_health 列
    # today_health为当天健康情况，next_health为次日健康情况，next_date为次日日期
    df['today_health'] = df[health_col]
    df['next_health'] = df[health_col].shift(-1)
    df['next_date'] = df[date_col].shift(-1)

    # 5. 标记拉稀（仅当日期连续才考虑次日，否则只考虑当天）
    # 规则：如果当天和次日日期连续，则当天食物与当天和次日健康情况都有关联
    #      如果不连续，只考虑当天健康情况
    def diarrhea_flag(row):
        today = is_diarrhea(row['today_health'], p_good, p_bad)
        # 判断 next_date 是否为下一天
        if pd.notna(row['next_date']) and (row['next_date'] - row[date_col]).days == 1:
            nextd = is_diarrhea(row['next_health'], p_good, p_bad)
        else:
            nextd = np.nan
        # 只要当天或次日有拉稀就算1
        if today == 1 or nextd == 1:
            return 1
        # 当天和次日都正常或无记录，算0
        elif today == 0 and (np.isnan(nextd) or nextd == 0):
            return 0
        # 当天无记录，次日正常或无记录，也算0
        elif np.isnan(today) and (np.isnan(nextd) or nextd == 0):
            return 0
        else:
            return np.nan  # 其他情况算NaN

    df['diarrhea'] = df.apply(diarrhea_flag, axis=1)

    # 6. 丢弃无用行
    df = df.dropna(subset=[eat_col, 'diarrhea'])
    # 清洗：当天和次日健康状况都缺失的行视为无效，剔除
    df = df[~(df['today_health'].isna() & df['next_health'].isna())]
    # 只保留关键字段
    keep_cols = [date_col, eat_col, health_col, 'today_health', 'next_health', 'next_date', 'diarrhea']
    df_valid = df[keep_cols].copy()
    # 保存清洗后的有效数据表
    df_valid.to_csv('src/AI_Prediction/data/有效数据表.csv', index=False, encoding='utf-8-sig')

    # 用大模型分词和分类
    print("正在分析食物和餐厅...")

    def extract_food_and_restaurant(s):
        if not isinstance(s, str) or not s.strip():
            return []
        result = llm_classify(s)
        # 实时输出大模型返回结果
        print(f"模型结果: {result}")
        # 只保留食物和餐厅
        return (result.get("食物", []) or []) + (result.get("餐厅", []) or [])

    # 检查今天的大模型分析表是否已存在，若存在则直接读取，无需重复分析
    from datetime import datetime
    today_str = datetime.now().strftime('%Y-%m-%d')
    analysis_path = f'src/AI_Prediction/data/大模型分析表_{today_str}.csv'
    import os
    if os.path.exists(analysis_path):
        print(f"检测到今日分析表 {analysis_path}，直接读取...")
        df = pd.read_csv(analysis_path, encoding='utf-8-sig')
    else:
        df['words'] = df[eat_col].map(extract_food_and_restaurant)
        df = df.explode('words')
        df = df[df['words'].notna() & (df['words'] != '')]
        keep_cols_analysis = [date_col, eat_col, health_col, 'today_health', 'next_health', 'next_date', 'diarrhea', 'words']
        df_analysis = df[keep_cols_analysis].copy()
        df_analysis.to_csv(analysis_path, index=False, encoding='utf-8-sig')
        print(f"已生成今日分析表 {analysis_path}")

    # 用大模型结构化餐次和健康描述
    print("正在结构化餐次和健康描述...")
    meal_cols = ["早餐", "午餐", "晚餐", "小吃"]
    meal_records = []
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
    # 展开拉稀事件为一行一事件
    meal_df = meal_df.explode('拉稀事件').reset_index(drop=True)
    if not meal_df.empty:
        meal_df['拉稀次数'] = meal_df['拉稀事件'].apply(lambda x: x.get('次数') if isinstance(x, dict) else None)
        meal_df['拉稀程度'] = meal_df['拉稀事件'].apply(lambda x: x.get('程度') if isinstance(x, dict) else None)
        meal_df['拉稀时间'] = meal_df['拉稀事件'].apply(lambda x: x.get('时间') if isinstance(x, dict) else None)
    # 保存明细表
    meal_df.to_csv('src/AI_Prediction/data/餐次食物拉稀明细表.csv', index=False, encoding='utf-8-sig')
    print('已保存餐次-食物-拉稀明细表')
    # 统计分析：每个餐次-食物的拉稀概率、次数、严重程度分布
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

    # 7. 分组聚合
    # 统计每个食物关键词的总出现次数和拉稀次数
    stats = df.groupby('words').agg(
        总出现次数=('words', 'size'),
        拉稀次数=('diarrhea', 'sum')
    )
    # 计算拉稀率（百分比字符串）
    stats['拉稀率'] = (stats['拉稀次数'] / stats['总出现次数']).map("{:.2%}".format)

    # 8. 排序并输出
    # 先将拉稀率转为浮点数用于排序，排序后去掉临时列
    result = (
        stats.assign(_rate=stats['拉稀率'].str.rstrip('%').astype(float))
        .sort_values(['总出现次数', '_rate'], ascending=[False, False])  # 先按总出现次数降序，再按拉稀率降序
        .drop(columns=['_rate'])
        .reset_index()
        .rename(columns={'words': '食物关键词'})
    )
    # 打印对齐的表格
    print(result.to_string(index=False, justify="center"))
    # 输出到csv文件
    result.to_csv('src/AI_Prediction/data/食物过敏分析表.csv', index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    main()
