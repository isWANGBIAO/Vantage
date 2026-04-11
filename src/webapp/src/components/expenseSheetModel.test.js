import assert from 'node:assert/strict';
import test from 'node:test';

import { buildExpenseSheetViewModel } from './expenseSheetModel.js';

test('buildExpenseSheetViewModel tolerates a null payload before data loads', () => {
  const viewModel = buildExpenseSheetViewModel(null);

  assert.equal(viewModel.meta.fileName, 'Balance Sheet.xlsx');
  assert.equal(viewModel.meta.sheetCount, 0);
  assert.equal(viewModel.rawSheets.length, 0);
  assert.equal(viewModel.defaultRawSheetName, '');
  assert.equal(viewModel.recentSpending.length, 0);
});

test('buildExpenseSheetViewModel derives dashboard sections from workbook payload', () => {
  const payload = {
    source: {
      path: 'C:\\Users\\97012\\OneDrive\\Mine\\Balance Sheet.xlsx',
      updated_at: '2026-04-11 18:46:33',
      sheet_count: 4,
    },
    summary: {
      time_cost: {
        daily_average: 200,
      },
      assets: {
        cash_and_stock: {
          value: 6000,
        },
      },
      budget: {
        monthly_required: 1200,
        monthly_optional: 300,
      },
    },
    sheets: [
      {
        name: '开销',
        columns: ['日期', '期间支出', '日均支出', '收入说明', '大支出说明'],
        rows: [
          ['2026-04-05', 260, 130, '', '买显示器支架'],
          ['2026-04-10', 120, 60, '报销到账', ''],
          ['2026-04-11', '', '', '', ''],
        ],
        row_count: 3,
        truncated: false,
      },
      {
        name: 'Budget',
        columns: ['项目类型', '项目', '是否必须', '月消费', '每月', '每日'],
        rows: [
          ['其他', 'chatgpt pro', '必须', 1200, 1200, 39.45],
          ['衣', '鞋子', '非必须', 300, 300, 10],
          [null, null, null, null, null, null],
        ],
        row_count: 3,
        truncated: false,
      },
      {
        name: '人情',
        columns: ['日期', '内容', '金额'],
        rows: [
          ['2025-01-27', '北京烤鸭', 310],
          [null, null, null],
        ],
        row_count: 2,
        truncated: false,
      },
      {
        name: 'Asset',
        columns: ['名称（1000元以上）', '数量', '单价', '总价'],
        rows: [
          ['Mac mini', 1, 4692, 4692],
          [null, null, null, 0],
        ],
        row_count: 2,
        truncated: false,
      },
    ],
  };

  const viewModel = buildExpenseSheetViewModel(payload);

  assert.equal(viewModel.meta.fileName, 'Balance Sheet.xlsx');
  assert.equal(viewModel.meta.sheetCount, 4);
  assert.equal(viewModel.kpis.find((item) => item.id === 'coverageDays').value, 30);
  assert.equal(viewModel.recentSpending[0].date, '2026-04-10');
  assert.equal(viewModel.recentSpending[1].note, '买显示器支架');
  assert.equal(viewModel.budget.groups.length, 2);
  assert.equal(viewModel.budget.groups[0].items[0].name, 'chatgpt pro');
  assert.equal(viewModel.assets.items.length, 1);
  assert.equal(viewModel.assets.items[0].name, 'Mac mini');
  assert.equal(viewModel.socialEvents.items.length, 1);
  assert.equal(viewModel.rawSheets.length, 4);
});
