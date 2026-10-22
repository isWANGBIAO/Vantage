import assert from 'node:assert/strict';
import test from 'node:test';
import { buildExpenseSheetViewModel } from './expenseSheetModel.js';

test('legal finance payload without a Budget sheet or summary renders', () => {
  const vm = buildExpenseSheetViewModel({ summary: { budget: null }, sheets: [] });
  assert.equal(vm.budget.monthlyRequired, null);
  assert.deepEqual(vm.budget.groups, []);
});

test('unknown amounts remain unknown but a measured zero remains zero', () => {
  for (const value of [null, '', 'unknown', 0]) {
    const vm = buildExpenseSheetViewModel({ sheets: [
      { name: 'Asset', columns: ['名称', '总价'], rows: [['Synthetic item', value]] },
      { name: '人情', columns: ['内容', '金额'], rows: [['Synthetic event', value]] },
    ] });
    assert.equal(vm.assets.totalValue, value === 0 ? 0 : null);
    assert.equal(vm.socialEvents.totalAmount, value === 0 ? 0 : null);
  }
});

test('money text retains accounting and Unicode signs and scientific notation', () => {
  const vm = buildExpenseSheetViewModel({ sheets: [{ name: 'Asset', columns: ['名称', '总价'], rows: [
    ['Exponent', '1e3'], ['Unicode', '−1,200.50'], ['Accounting', '(1,200)'], ['Invalid', 'abc123'],
  ] }] });
  const amounts = Object.fromEntries(vm.assets.items.map((item) => [item.name, item.totalPrice]));
  assert.deepEqual(amounts, { Exponent: 1000, Unicode: -1200.5, Accounting: -1200, Invalid: null });
});

test('daily-only budget uses backend calendar period and optional variants', () => {
  for (const days of [28, 29, 30, 31]) {
    const vm = buildExpenseSheetViewModel({ summary: { budget: { days_in_month: days } }, sheets: [{
      name: 'Budget', columns: ['项目', '是否必须', '每日'], rows: [['Optional A', '非必需', 10], ['Optional B', '不必需', 5]],
    }] });
    assert.equal(vm.budget.groups[0].total, 15 * days);
    assert(vm.budget.topItems.every((item) => item.required === false));
  }
});
