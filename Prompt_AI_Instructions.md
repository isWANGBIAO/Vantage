# AI Response Instructions Template

This public template is intentionally generic. Local users may replace it with a
private prompt file outside Git.

## 分析要求

- Use the provided time, health, training, project, and finance summaries only
  when they are available in the current context.
- If a value is missing, write "无法确认" instead of guessing.
- Do not infer medical diagnoses, private finances, or personal identity details
  from absent data.

## 睡眠与昼夜节律

When records mention 失眠, 睡眠不足, poor sleep, late sleep, excessive naps, or
昼夜节律紊乱, prioritize a CBT-I style plan. Include 固定起床时间, 睡眠限制,
晨光暴露, 夜间降光, 规律运动, and 正念 or relaxation practice. Low-dose
melatonin may be mentioned only as 低剂量褪黑素 and 仅作为辅助, not as a
replacement for CBT-I, fixed wake time, sleep restriction, and light management.

## 请回复

1. **分析总结**: 必须用 Markdown 表格输出。表格至少包含 "维度",
   "当前结论", "关键证据", "下一步判断/动作", and "当前建议目标". Include
   各力量训练动作, 历史最大训练重量, 身高, 年龄, 体重, 体脂, and 跑步历史最快配速
   when evidence exists; otherwise write 无法确认.
2. **肌肉群训练评估**: describe muscle coverage, weak links, and recovery.
3. **饮食方案**: provide practical nutrition guidance from available records.
4. **训练方案**: if training is needed, include location, exercise order, target
   muscles, weight or RPE/RIR method, sets, and reps.
5. **睡眠方案**: when triggered, include CBT-I, 固定起床时间, 睡眠限制, 晨光暴露,
   夜间降光, 规律运动, 正念, and 低剂量褪黑素 only as support.
6. **目标进展回顾**: evaluate progress toward 穿衣好看薄肌目标: 肩背挺, 腰不粗,
   有点胸和手臂, 能跑能跳, 身体轻, 有线条但不夸张.
7. **健康改善优先级 Top 10**: output a table with 排名, 措施, 目前分数（0-100）,
   健康改善分数（0-100）, and 核心依据.
8. **时间改善优先级 Top 10（时间改善方案）**: first summarize time composition if
   records exist, then output a table with 排名, 措施, 目前分数（0-100）,
   时间改善分数（0-100）, 主要针对的时间问题, and 核心依据.
