function isEnglishLanguage(language) {
  return String(language || '').toLowerCase().startsWith('en');
}

export function localizeExpenseSuggestion(value, language) {
  if (!isEnglishLanguage(language) || typeof value !== 'string') {
    return value;
  }

  let match = value.match(/^时间成本：全天均摊每分钟约 (.+)，建议把高价值任务放在高专注时段，降低低价值碎片时间。$/);
  if (match) {
    return `Time cost: the all-day average is about ${match[1]} per minute. Put high-value tasks in high-focus periods and reduce low-value fragmented time.`;
  }

  match = value.match(/^月度均摊每日约 (.+)，可结合预算上限设定每日支出阈值。$/);
  if (match) {
    return `Monthly spending averages about ${match[1]} per day. Use the budget cap to set a daily spending threshold.`;
  }

  match = value.match(/^现金\+股票可覆盖约 (.+) 天日常开销，可据此设定安全垫目标。$/);
  if (match) {
    return `Cash plus stocks can cover about ${match[1]} days of daily spending. Use that to set a safety buffer target.`;
  }

  match = value.match(/^每月必须开支约 (.+)，建议优先保障基础支出并定期复盘。$/);
  if (match) {
    return `Required monthly spending is about ${match[1]}. Prioritize baseline expenses and review them regularly.`;
  }

  match = value.match(/^每月非必须开支约 (.+)，可设置弹性上限以控制超支。$/);
  if (match) {
    return `Optional monthly spending is about ${match[1]}. Set a flexible cap to control overspending.`;
  }

  const exactCopy = {
    '固定资产占比偏高，建议评估折旧压力和流动性风险，适度提升现金/可变资产比例。':
      'Fixed assets take up a high share. Review depreciation pressure and liquidity risk, then raise the cash or flexible-asset share where appropriate.',
    '固定资产占比较低，可结合长期规划评估必要的设备/能力投资。':
      'Fixed assets take up a low share. Use long-term planning to decide whether equipment or capability investment is needed.',
    '流动资产占比偏低，建议提高现金或短期可变资产以增强抗风险能力。':
      'Current assets take up a low share. Increase cash or short-term flexible assets to improve resilience.',
    '负债率偏高，建议优先偿还高利率负债，降低资金压力。':
      'The debt ratio is high. Prioritize high-interest debt to reduce financial pressure.',
    '当前可用指标较少，建议补充‘日均支出/资产/负债’等字段以获得更精确的优化建议。':
      'There are too few available metrics. Add fields such as daily spending, assets, and liabilities for more precise optimization suggestions.',
  };

  return exactCopy[value] || value;
}
