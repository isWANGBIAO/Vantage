import test from 'node:test';
import assert from 'node:assert/strict';

import { localizeExpenseSuggestion } from './expenseLocalization.js';

test('localizeExpenseSuggestion translates generated backend suggestions in English mode', () => {
  assert.equal(
    localizeExpenseSuggestion(
      '时间成本：全天均摊每分钟约 1.25，建议把高价值任务放在高专注时段，降低低价值碎片时间。',
      'en-US',
    ),
    'Time cost: the all-day average is about 1.25 per minute. Put high-value tasks in high-focus periods and reduce low-value fragmented time.',
  );

  assert.equal(
    localizeExpenseSuggestion('固定资产占比偏高，建议评估折旧压力和流动性风险，适度提升现金/可变资产比例。', 'en-US'),
    'Fixed assets take up a high share. Review depreciation pressure and liquidity risk, then raise the cash or flexible-asset share where appropriate.',
  );

  assert.equal(
    localizeExpenseSuggestion('现金+股票可覆盖约 58.4 天日常开销，可据此设定安全垫目标。', 'en-US'),
    'Cash plus stocks can cover about 58.4 days of daily spending. Use that to set a safety buffer target.',
  );
});

test('localizeExpenseSuggestion keeps Chinese mode unchanged', () => {
  const text = '每月必须开支约 3200.00，建议优先保障基础支出并定期复盘。';
  assert.equal(localizeExpenseSuggestion(text, 'zh-CN'), text);
});
