const ENGLISH_TEXT = {
  '体重 / 体脂率 / 脂肪质量趋势': 'Weight / Body Fat / Fat Mass Trend',
  '保留现有计算口径，用交互式多轴折线替代多张静态体重图。':
    'Keep the current calculation method, but replace several static weight charts with one interactive multi-axis line chart.',
  '作息趋势': 'Sleep Schedule Trend',
  '把主睡眠的入睡时间和起床时间放到同一条时间轴上，并按起床当天归属，直接看作息是提前还是后移。':
    'Place bedtime and wake time on the same time axis, bucketed by wake-up day, so schedule drift is visible directly.',
  '每日时间分配': 'Daily Time Allocation',
  '把睡眠、手机屏幕和剩余时间放进同一张可缩放堆叠图里，替代原始静态柱状图。':
    'Sleep, phone screen time, and remaining hours are stacked into one zoomable chart instead of a static bar plot.',
  '手机屏幕时间 vs 剩余时间': 'Phone Screen Time vs Remaining Time',
  '保留原始数值与均线，对比屏幕占用和当天可支配时间的相对变化。':
    'Compare raw values and moving averages to see how phone screen time changes against discretionary time.',
  '时间均线 vs 目标': 'Time Averages vs Targets',
  '把睡眠、屏幕和剩余时间放进同一个目标对照图，直接看长期偏离方向。':
    'Put sleep, screen time, and remaining hours against targets in one chart to show long-term deviation.',
  '距离目标的差距': 'Gap to Targets',
  '把三条时间目标统一换算成偏差值，负值和正值的变化会更直观。':
    'Convert the three time targets into deviation values so positive and negative movement is easier to read.',
  '目标达成率雷达图': 'Goal Achievement Radar',
  '保留原来的达成率口径，但把它做成交互式雷达图，便于一眼看结构性短板。':
    'Keep the existing achievement scoring method, but render it as an interactive radar chart to expose structural gaps.',
  'HHH 频率分布': 'HHH Frequency Distribution',
  '把历史散点直接做成交互式频率图，悬浮即可看具体时间点和强度。':
    'Render historical points as an interactive frequency chart so each timestamp and intensity is available on hover.',
  'HHH 间隔趋势': 'HHH Interval Trend',
  '把每次间隔天数直接拉成可对比折线，更适合看节奏是否在收敛或发散。':
    'Plot interval days as comparable lines to show whether the rhythm is tightening or spreading out.',
  '资产与支出': 'Assets and Spending',
  '把总资产、分账户资产和日均支出放进同一张可筛选图，而不是只看一张静态资金曲线。':
    'Combine total assets, account-level assets, and daily spending into one filterable chart instead of one static balance curve.',
  '跑步配速-心率耦合': 'Running Pace and Heart Rate Coupling',
  '把配速、心率与距离放在同一时间轴上，直接观察节奏变化时心肺负荷是否同步变化。':
    'Put pace, heart rate, and distance on one timeline to see whether cardio load moves with pace changes.',
  '跑步技术结构': 'Running Form Structure',
  '把单次用时、步频、步幅放在一起，更容易看清动作结构是否稳定，而不是只看单一配速。':
    'Combine duration, cadence, and stride length to judge running form stability beyond pace alone.',
  '这里按速度 ÷ 心率计算 HRC，单位是 m/beat。数值越高，表示单位心搏支持的前进效率越高。':
    'HRC is calculated as speed divided by heart rate, in m/beat. Higher values mean each heartbeat supports more forward movement.',

  '体重 (kg)': 'Weight (kg)',
  '体脂率 (%)': 'Body Fat (%)',
  '脂肪质量 (kg)': 'Fat Mass (kg)',
  '体重': 'Weight',
  '平均体重': 'Average Weight',
  '体脂率': 'Body Fat',
  '平均体脂率': 'Average Body Fat',
  '脂肪质量': 'Fat Mass',
  '时间': 'Time',
  '小时': 'Hours',
  '距离目标的差值 (小时)': 'Difference from Target (hours)',
  '睡眠时间': 'Sleep Duration',
  '平均睡眠时间': 'Average Sleep Duration',
  '目标睡眠时间 8h': 'Target Sleep 8h',
  '平均睡眠时间 - 8h': 'Average Sleep Duration - 8h',
  '手机屏幕使用时间': 'Phone Screen Time',
  '手机屏幕时间': 'Phone Screen Time',
  '平均手机屏幕使用时间': 'Average Phone Screen Time',
  '目标屏幕时间 4h': 'Target Screen Time 4h',
  '平均手机屏幕使用时间 - 4h': 'Average Phone Screen Time - 4h',
  '剩余时间': 'Remaining Time',
  '平均剩余时间': 'Average Remaining Time',
  '目标剩余时间 12h': 'Target Remaining Time 12h',
  '平均剩余时间 - 12h': 'Average Remaining Time - 12h',
  '入睡时间': 'Bedtime',
  '起床时间': 'Wake Time',
  '目标达成率': 'Goal Achievement',
  '目标雷达': 'Goal Radar',
  '频次': 'Count',
  '性生活': 'Sex',
  '自慰': 'Masturbation',
  '第 N 次行为': 'Nth Activity',
  '间隔天数': 'Interval Days',
  '性生活间隔（天）': 'Sex Interval (days)',
  '自慰间隔（天）': 'Masturbation Interval (days)',
  '资产 (元)': 'Assets (RMB)',
  '日均支出 (元/天)': 'Daily Spending (RMB/day)',
  '当月收入': 'Monthly Income',
  '现金及现金等价物+股票': 'Cash and Equivalents + Stocks',
  '预测期末现金+股票': 'Projected Month-End Cash + Stocks',
  '支付宝资产': 'Alipay Assets',
  '银行卡资产': 'Bank Card Assets',
  '微信资产': 'WeChat Assets',
  '股票资产': 'Stocks',
  '日均支出': 'Daily Spending',
  '配速 (min/km)': 'Pace (min/km)',
  '心率 (bpm)': 'Heart Rate (bpm)',
  '距离 (km)': 'Distance (km)',
  '配速 Pace (min/km)': 'Pace (min/km)',
  '心率 Heart Rate (bpm)': 'Heart Rate (bpm)',
  '距离 Distance (km)': 'Distance (km)',
  '用时 (min)': 'Duration (min)',
  '步频 (spm)': 'Cadence (spm)',
  '步幅 (m)': 'Stride (m)',
  '用时 Duration (min)': 'Duration (min)',
  '步频 Cadence (spm)': 'Cadence (spm)',
  '步幅 Stride (m)': 'Stride (m)',

  '最新体重': 'Latest Weight',
  '最新体脂率': 'Latest Body Fat',
  '最新脂肪质量': 'Latest Fat Mass',
  '最近入睡': 'Latest Bedtime',
  '最近起床': 'Latest Wake Time',
  '平均入睡': 'Average Bedtime',
  '平均起床': 'Average Wake Time',
  '样本天数': 'Sample Days',
  '平均睡眠': 'Average Sleep',
  '平均屏幕时间': 'Average Screen Time',
  '性生活总次数': 'Total Sex Count',
  '自慰总次数': 'Total Masturbation Count',
  '性生活平均间隔': 'Average Sex Interval',
  '自慰平均间隔': 'Average Masturbation Interval',
  '最新总资产': 'Latest Total Assets',
  '最新日均支出': 'Latest Daily Spending',
  '最新配速': 'Latest Pace',
  '最新距离': 'Latest Distance',
  '总跑量': 'Total Distance',
  '总跑步时间': 'Total Running Time',
  '最新心率': 'Latest Heart Rate',
  '最近用时': 'Latest Duration',
  '平均步频': 'Average Cadence',
  '平均步幅': 'Average Stride',
  '最新 HRC': 'Latest HRC',
  '最佳 HRC': 'Best HRC',
  '对应心率': 'Matching Heart Rate',

  '跑步主图存在未完整提取的记录': 'Running main chart has incompletely extracted records',
  '这些记录会让配速 / 心率 / 距离出现断点。请按原文修正 Excel 后再 refresh charts。':
    'These records can create gaps in pace, heart rate, or distance. Fix the Excel source text, then refresh charts.',
  '跑步技术结构存在未完整提取的记录': 'Running form chart has incompletely extracted records',
  '这些记录会让用时 / 步频 / 步幅出现断点。请补齐原始文本后再 refresh charts。':
    'These records can create gaps in duration, cadence, or stride. Complete the source text, then refresh charts.',
  'HRC 分析存在未完整提取的记录': 'HRC analysis has incompletely extracted records',
  '这些记录无法可靠计算 HRC，会直接影响趋势判断。请优先修正缺失字段。':
    'These records cannot produce reliable HRC values and will affect trend judgment. Fix missing fields first.',
  '已排除的异常跑步记录': 'Excluded anomalous running records',
  '这些记录未参与主跑步图 / 心率分析 / 技术结构图计算，避免明显失真的脏数据污染趋势。':
    'These records were excluded from the main running, heart-rate, and form charts to keep distorted source data out of the trends.',
  '这些记录未参与时间类图表计算。请修改 Excel 源数据后刷新 Plots 页面。':
    'These rows were excluded from time charts. Fix the Excel source data, then refresh the Plots page.',
  '关键字段异常': 'key field invalid',
  '时间数据无效': 'invalid time data',
  '未知': 'unknown',
  '未知日期': 'unknown date',
  '空': 'empty',
};

function isEnglishLanguage(language) {
  return String(language || '').toLowerCase().startsWith('en');
}

function localizeIssueSubject(value) {
  const subject = String(value || '').trim();
  const subjects = {
    配速: 'pace',
    心率: 'heart rate',
    距离: 'distance',
    用时: 'duration',
    '用时/配速': 'duration/pace',
    步频: 'cadence',
    步幅: 'stride',
    HRC: 'HRC',
  };
  return subjects[subject] || localizePlotText(subject, 'en-US');
}

function localizePatternText(text) {
  if (text.includes('、')) {
    const parts = text.split('、');
    const localizedParts = parts.map((part) => localizePlotText(part, 'en-US'));
    if (localizedParts.some((part, index) => part !== parts[index])) {
      return localizedParts.join(', ');
    }
  }

  let match = text.match(/^近 (\d+) 天达成率$/);
  if (match) {
    return `Last ${match[1]} Days Achievement`;
  }

  match = text.match(/^(\d+)次均值$/);
  if (match) {
    return `${match[1]}-Sample Average`;
  }

  match = text.match(/^已跳过 (\d+) 条异常时间数据$/);
  if (match) {
    return `Skipped ${match[1]} anomalous time rows`;
  }

  match = text.match(/^其余 (\d+) 条异常记录已省略，请直接检查 Excel 源数据。$/);
  if (match) {
    return `${match[1]} more anomalous rows are hidden. Inspect the Excel source data directly.`;
  }

  match = text.match(/^缺少 (.+)$/);
  if (match) {
    return `Missing ${localizeIssueSubject(match[1])}`;
  }

  match = text.match(/^心率异常值 (\d+)$/);
  if (match) {
    return `Abnormal heart rate ${match[1]}`;
  }

  match = text.match(/^距离 < 1 km（(.+)）$/);
  if (match) {
    return `Distance < 1 km (${localizeUnitText(match[1])})`;
  }

  match = text.match(/^配速 > 10:00\/km（当前 (.+)\/km）$/);
  if (match) {
    return `Pace > 10:00/km (current ${match[1]}/km)`;
  }

  match = text.match(/^用时超出阈值（上限 (.+)，当前 (.+)）$/);
  if (match) {
    return `Duration exceeds threshold (limit ${localizeUnitText(match[1])}, current ${localizeUnitText(match[2])})`;
  }

  match = text.match(/^(.+)：睡眠时间 (.+)，手机屏幕使用时间 (.+)，原因：(.+)$/);
  if (match) {
    const [, date, sleep, screen, reason] = match;
    return `${localizePlotText(date, 'en-US')}: sleep time ${localizePlotText(sleep, 'en-US')}, phone screen time ${localizePlotText(screen, 'en-US')}, reason: ${localizePlotText(reason, 'en-US')}`;
  }

  match = text.match(/^(.+)：(.+)；原文：(.+)$/);
  if (match) {
    const [, date, issue, source] = match;
    return `${localizePlotText(date, 'en-US')}: ${localizePlotText(issue, 'en-US')}; source: ${localizePlotText(source, 'en-US')}`;
  }

  return null;
}

function localizeUnitText(text) {
  return text
    .replace(/\/天/g, '/day')
    .replace(/(\d+(?:\.\d+)?)\s*天/g, '$1 days')
    .replace(/(\d+(?:\.\d+)?)\s*小时(\d{1,2})\s*分钟/g, '$1 h $2 min')
    .replace(/(\d+(?:\.\d+)?)\s*小时(\d{1,2})\s*分/g, '$1 h $2 min')
    .replace(/(\d+(?:\.\d+)?)\s*小时/g, '$1 hours')
    .replace(/(\d+(?:\.\d+)?)\s*分钟/g, '$1 min')
    .replace(/(\d+(?:\.\d+)?)\s*分(\d{1,2})\s*秒/g, '$1 min $2 sec');
}

export function localizePlotText(value, language) {
  if (!isEnglishLanguage(language) || typeof value !== 'string') {
    return value;
  }

  if (ENGLISH_TEXT[value]) {
    return ENGLISH_TEXT[value];
  }

  const patternText = localizePatternText(value);
  if (patternText) {
    return patternText;
  }

  return localizeUnitText(value);
}

function localizeObject(value, language) {
  if (Array.isArray(value)) {
    return value.map((item) => localizeObject(item, language));
  }

  if (!value || typeof value !== 'object') {
    return localizePlotText(value, language);
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, entryValue]) => [
      localizePlotText(key, language),
      localizeObject(entryValue, language),
    ]),
  );
}

function localizeSummaryItem(item, language) {
  if (!item || typeof item !== 'object') {
    return localizePlotText(item, language);
  }

  return {
    ...item,
    label: localizePlotText(item.label, language),
    value: localizePlotText(item.value, language),
    text: localizePlotText(item.text, language),
    unit: localizePlotText(item.unit, language),
    suffix: localizePlotText(item.suffix, language),
  };
}

export function localizePlotChart(chart, language) {
  if (!isEnglishLanguage(language) || !chart || typeof chart !== 'object') {
    return chart;
  }

  return {
    ...chart,
    title: localizePlotText(chart.title, language),
    description: localizePlotText(chart.description, language),
    message: localizePlotText(chart.message, language),
    error: localizePlotText(chart.error, language),
    summary: Array.isArray(chart.summary)
      ? chart.summary.map((item) => localizeSummaryItem(item, language))
      : chart.summary,
    option: localizeObject(chart.option || {}, language),
  };
}

function localizeWarning(warning, language) {
  if (!isEnglishLanguage(language) || !warning || typeof warning !== 'object') {
    return warning;
  }

  return {
    ...warning,
    title: localizePlotText(warning.title, language),
    message: localizePlotText(warning.message, language),
    detail: localizePlotText(warning.detail, language),
    details: Array.isArray(warning.details)
      ? warning.details.map((detail) => localizePlotText(detail, language))
      : warning.details,
    rows: Array.isArray(warning.rows)
      ? warning.rows.map((row) => localizePlotText(row, language))
      : warning.rows,
  };
}

export function localizePlotWarnings(warnings, language) {
  if (!Array.isArray(warnings)) {
    return [];
  }

  return warnings.map((warning) => localizeWarning(warning, language));
}
