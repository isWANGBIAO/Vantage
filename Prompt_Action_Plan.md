# Action Plan Prompt Template

Current time: {current_time}

Today's row:

{today_data_row}

Yesterday's row:

{yesterday_data_row}

Past 7 days:

{past_7_days_rows}

Future planned rows:

{future_planned_rows}

## Task

Create a concise daily plan in Chinese. Use only the evidence above and the
current conversation. If evidence is missing, write "无法确认".

## Required Structure

1. 今日状态判断
2. 过去 7 天训练分析: cover 训练频率, 肌群覆盖, 强度, 恢复状态, and whether the
   next step should be 补量、维持还是降量.
3. 今日行动计划: use a Markdown table with time, task, evidence, and fallback.
4. Sleep intervention when triggered: use CBT-I, 固定起床时间, 睡眠限制, 晨光暴露,
   夜间降光, 规律运动, 正念, and 低剂量褪黑素 仅作为辅助.
5. Risks and missing evidence.
