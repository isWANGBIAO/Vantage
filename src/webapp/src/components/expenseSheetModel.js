const EXPENSE_SHEET_NAMES = ['开销', 'expense'];
const BUDGET_SHEET_NAMES = ['budget', '预算'];
const ASSET_SHEET_NAMES = ['asset', '资产'];
const SOCIAL_SHEET_NAMES = ['人情'];

const REQUIRED_TOKENS = ['必须', '必需', '是', 'required', 'yes', 'y'];
const OPTIONAL_TOKENS = ['非必须', '不必须', '不是', '否', 'not required', 'optional', 'no', 'n'];
const DAY_MS = 24 * 60 * 60 * 1000;

function normalizeText(value) {
  return String(value ?? '').trim();
}

function normalizeSheetName(value) {
  return normalizeText(value).toLowerCase();
}

function compactFileName(path) {
  const text = normalizeText(path);
  if (!text) return 'Balance Sheet.xlsx';
  const parts = text.split(/[/\\]/).filter(Boolean);
  return parts.at(-1) || text;
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  const text = normalizeText(value);
  if (!text) return null;

  const cleaned = text.replace(/[^\d.-]/g, '');
  if (!cleaned || cleaned === '-' || cleaned === '.') return null;

  const number = Number(cleaned);
  return Number.isFinite(number) ? number : null;
}

function roundMetric(value) {
  if (value === null || value === undefined) return null;
  return Math.round(value * 10) / 10;
}

function parseDateValue(value) {
  const text = normalizeText(value);
  if (!text) return null;

  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) {
    const timestamp = Date.parse(text.replace(' ', 'T'));
    return Number.isNaN(timestamp) ? null : timestamp;
  }

  const timestamp = Date.parse(text);
  return Number.isNaN(timestamp) ? null : timestamp;
}

function resolveAnchorTimestamp(payload, options = {}) {
  if (Number.isFinite(Number(options.anchorTimestamp))) {
    return Number(options.anchorTimestamp);
  }

  const sourceTimestamp = parseDateValue(payload?.source?.updated_at);
  if (sourceTimestamp !== null) {
    return sourceTimestamp;
  }

  return Date.now();
}

function findSheet(sheets, candidates) {
  const normalizedCandidates = candidates.map((item) => item.toLowerCase());
  return (
    sheets.find((sheet) => normalizedCandidates.includes(normalizeSheetName(sheet.name))) ||
    sheets.find((sheet) =>
      normalizedCandidates.some((candidate) => normalizeSheetName(sheet.name).includes(candidate))
    ) ||
    null
  );
}

function getColumnIndex(sheet, aliases) {
  const normalizedAliases = aliases.map((alias) => alias.toLowerCase());

  const exactIndex = sheet.columns.findIndex((column) =>
    normalizedAliases.includes(normalizeText(column).toLowerCase())
  );
  if (exactIndex >= 0) return exactIndex;

  return sheet.columns.findIndex((column) =>
    normalizedAliases.some((alias) => normalizeText(column).toLowerCase().includes(alias))
  );
}

function getCell(sheet, row, aliases) {
  const index = getColumnIndex(sheet, aliases);
  if (index < 0) return null;
  return row[index];
}

function parseRequiredFlag(value) {
  const text = normalizeText(value).toLowerCase();
  if (!text) return null;

  const matches = (token) => {
    const normalizedToken = token.toLowerCase();
    if (['是', '否', 'yes', 'no', 'y', 'n', 'required', 'optional'].includes(normalizedToken)) {
      return text === normalizedToken;
    }
    return text.includes(normalizedToken);
  };

  if (OPTIONAL_TOKENS.some(matches)) return false;
  if (REQUIRED_TOKENS.some(matches)) return true;
  return null;
}

function getMonthlyBudgetValue(sheet, row) {
  const monthlyValue = toNumber(getCell(sheet, row, ['每月', '月消费', 'monthly']));
  if (monthlyValue !== null) return monthlyValue;

  const yearlyValue = toNumber(getCell(sheet, row, ['一年合计', '年消费', 'annual']));
  if (yearlyValue !== null) return yearlyValue / 12;

  const dailyValue = toNumber(getCell(sheet, row, ['每日', '日消费', 'daily']));
  if (dailyValue !== null) return dailyValue * 30;

  return null;
}

function buildRecentSpending(sheet, anchorTimestamp) {
  if (!sheet) return [];

  return sheet.rows
    .map((row) => {
      const date = normalizeText(getCell(sheet, row, ['日期', 'date']));
      const sortValue = parseDateValue(date);
      const periodSpend = toNumber(getCell(sheet, row, ['期间支出', '支出']));
      const dailyAverage = toNumber(getCell(sheet, row, ['日均支出', '日均开销']));
      const incomeNote = normalizeText(getCell(sheet, row, ['收入说明']));
      const note = normalizeText(getCell(sheet, row, ['大支出说明']));

      if (!date || sortValue === null) return null;
      if (sortValue > anchorTimestamp) return null;
      if (periodSpend === null && dailyAverage === null && !incomeNote && !note) return null;

      return {
        date,
        timestamp: sortValue,
        periodSpend,
        dailyAverage,
        incomeNote,
        note,
        sortValue,
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.sortValue - left.sortValue)
    .slice(0, 6);
}

function buildBudgetSection(sheet, summaryBudget = {}) {
  if (!sheet) {
    return {
      monthlyRequired: summaryBudget.monthly_required ?? null,
      monthlyOptional: summaryBudget.monthly_optional ?? null,
      groups: [],
      topItems: [],
    };
  }

  const items = sheet.rows
    .map((row) => {
      const name = normalizeText(getCell(sheet, row, ['项目', 'item']));
      if (!name) return null;

      const category = normalizeText(getCell(sheet, row, ['项目类型', '分类', 'category'])) || '未分类';
      const required = parseRequiredFlag(getCell(sheet, row, ['是否必须', '必需', 'required']));
      const monthlyValue = getMonthlyBudgetValue(sheet, row);
      const dailyValue = toNumber(getCell(sheet, row, ['每日', '日消费', 'daily']));

      if (monthlyValue === null && dailyValue === null) return null;

      return {
        category,
        name,
        required,
        monthlyValue,
        dailyValue,
      };
    })
    .filter(Boolean)
    .sort((left, right) => (right.monthlyValue ?? 0) - (left.monthlyValue ?? 0));

  const groupsMap = new Map();
  for (const item of items) {
    const current = groupsMap.get(item.category) || {
      name: item.category,
      total: 0,
      items: [],
    };
    current.total += item.monthlyValue ?? 0;
    current.items.push(item);
    groupsMap.set(item.category, current);
  }

  const groups = [...groupsMap.values()].sort((left, right) => right.total - left.total);

  return {
    monthlyRequired: summaryBudget.monthly_required ?? null,
    monthlyOptional: summaryBudget.monthly_optional ?? null,
    groups,
    topItems: items.slice(0, 6),
  };
}

function buildAssetSection(sheet) {
  if (!sheet) {
    return {
      totalValue: null,
      items: [],
    };
  }

  const items = sheet.rows
    .map((row) => {
      const name = normalizeText(getCell(sheet, row, ['名称', '名称（1000元以上）', 'name']));
      if (!name) return null;

      const quantity = toNumber(getCell(sheet, row, ['数量', 'qty']));
      const unitPrice = toNumber(getCell(sheet, row, ['单价', 'unit']));
      const totalPrice =
        toNumber(getCell(sheet, row, ['总价', 'total'])) ??
        (quantity !== null && unitPrice !== null ? quantity * unitPrice : null);

      return {
        name,
        quantity,
        unitPrice,
        totalPrice,
      };
    })
    .filter(Boolean)
    .sort((left, right) => (right.totalPrice ?? 0) - (left.totalPrice ?? 0));

  const totalValue = items.reduce((sum, item) => sum + (item.totalPrice ?? 0), 0);

  return {
    totalValue: items.length ? totalValue : null,
    items,
  };
}

function buildSocialEvents(sheet) {
  if (!sheet) {
    return {
      totalAmount: null,
      items: [],
    };
  }

  const items = sheet.rows
    .map((row) => {
      const date = normalizeText(getCell(sheet, row, ['日期', 'date']));
      const title = normalizeText(getCell(sheet, row, ['内容', '项目', 'content']));
      const amount = toNumber(getCell(sheet, row, ['金额', 'amount']));
      const sortValue = parseDateValue(date) ?? 0;

      if (!title) return null;

      return {
        date,
        title,
        amount,
        sortValue,
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.sortValue - left.sortValue);

  const totalAmount = items.reduce((sum, item) => sum + (item.amount ?? 0), 0);

  return {
    totalAmount: items.length ? totalAmount : null,
    items,
  };
}

function getTrendDefaultRange(points) {
  if (points.length < 2) return 'all';

  const spanDays = (points[points.length - 1].timestamp - points[0].timestamp) / DAY_MS;
  if (spanDays > 365) return '1y';
  if (spanDays > 183) return '6m';
  return 'all';
}

function normalizeTrendPoint(point, anchorTimestamp) {
  const date = normalizeText(point?.date);
  const timestamp = parseDateValue(date);
  const balance = toNumber(point?.balance ?? point?.cash_and_stock ?? point?.cashAndStock);
  const dailyAverage = toNumber(point?.daily_average ?? point?.dailyAverage);
  const periodSpend = toNumber(point?.period_spend ?? point?.periodSpend ?? point?.spend);

  if (!date || timestamp === null) return null;
  if (timestamp > anchorTimestamp) return null;
  if (balance === null && dailyAverage === null && periodSpend === null) return null;

  return {
    date,
    timestamp,
    balance,
    dailyAverage,
    periodSpend,
  };
}

function buildSheetTrendPoints(sheet, anchorTimestamp) {
  if (!sheet) return [];

  return sheet.rows
    .map((row) =>
      normalizeTrendPoint(
        {
          date: getCell(sheet, row, ['日期', 'date']),
          balance: getCell(sheet, row, [
            '现金及现金等价物+股票',
            '现金及现金等价物',
            '现金',
            '股票',
          ]),
          daily_average: getCell(sheet, row, ['日均支出', '日均开销']),
          period_spend: getCell(sheet, row, ['期间支出', '支出']),
        },
        anchorTimestamp
      )
    )
    .filter(Boolean)
    .sort((left, right) => left.timestamp - right.timestamp);
}

function buildTrendPoints(payload, sheet, anchorTimestamp) {
  const payloadTrendPoints = Array.isArray(payload?.trend_points)
    ? payload.trend_points
    : Array.isArray(payload?.expense_trend_points)
      ? payload.expense_trend_points
      : [];

  const normalizedPayloadPoints = payloadTrendPoints
    .map((point) => normalizeTrendPoint(point, anchorTimestamp))
    .filter(Boolean)
    .sort((left, right) => left.timestamp - right.timestamp);

  if (normalizedPayloadPoints.length) {
    return normalizedPayloadPoints;
  }

  return buildSheetTrendPoints(sheet, anchorTimestamp);
}

function buildTrendChartSection(payload, sheet, summary = {}, anchorTimestamp) {
  const points = buildTrendPoints(payload, sheet, anchorTimestamp);

  if (!points.length) {
    return {
      points: [],
      summary: {
        latestBalance: null,
        latestDailyAverage: null,
        balanceChange: null,
        coverageDays: null,
        latestDate: '--',
      },
      defaultRange: 'all',
    };
  }

  const latestPoint = points.at(-1) || null;
  const firstBalancePoint = points.find((point) => point.balance !== null) || null;
  const latestBalancePoint = [...points].reverse().find((point) => point.balance !== null) || null;
  const latestSpendPoint = [...points].reverse().find((point) => point.dailyAverage !== null) || null;

  const latestBalance =
    latestBalancePoint?.balance ?? toNumber(summary?.assets?.cash_and_stock?.value);
  const latestDailyAverage =
    latestSpendPoint?.dailyAverage ?? toNumber(summary?.time_cost?.daily_average);
  const balanceChange =
    firstBalancePoint && latestBalance !== null
      ? roundMetric(latestBalance - (firstBalancePoint.balance ?? 0))
      : null;
  const coverageDays =
    latestBalance !== null && latestDailyAverage !== null && latestDailyAverage > 0
      ? roundMetric(latestBalance / latestDailyAverage)
      : null;

  return {
    points,
    summary: {
      latestBalance,
      latestDailyAverage,
      balanceChange,
      coverageDays,
      latestDate: latestPoint?.date ?? '--',
    },
    defaultRange: getTrendDefaultRange(points),
  };
}

function normalizeForecastPoint(point) {
  const date = normalizeText(point?.date);
  const timestamp = parseDateValue(date);
  if (!date || timestamp === null) return null;

  const fixedIncome = toNumber(point?.fixed_income ?? point?.fixedIncome);
  const extraIncome = toNumber(point?.extra_income ?? point?.extraIncome);
  const totalIncome = toNumber(point?.total_income ?? point?.totalIncome);
  const plannedSpend = toNumber(point?.planned_spend ?? point?.plannedSpend);
  const netCashFlow = toNumber(point?.net_cash_flow ?? point?.netCashFlow);
  const projectedBalance = toNumber(point?.projected_balance ?? point?.projectedBalance);

  if (
    fixedIncome === null &&
    extraIncome === null &&
    totalIncome === null &&
    plannedSpend === null &&
    netCashFlow === null &&
    projectedBalance === null
  ) {
    return null;
  }

  return {
    date,
    timestamp,
    fixedIncome,
    extraIncome,
    totalIncome,
    plannedSpend,
    netCashFlow,
    projectedBalance,
  };
}

function buildSheetForecastPoints(sheet, anchorTimestamp) {
  if (!sheet) return [];

  return sheet.rows
    .map((row) => {
      const date = normalizeText(getCell(sheet, row, ['日期', 'date']));
      const timestamp = parseDateValue(date);
      if (!date || timestamp === null) return null;

      const recordType = normalizeText(getCell(sheet, row, ['记录类型', '数据类型', '类型', 'record_type']));
      const markedForecast = /预测|计划|forecast|plan/i.test(recordType);
      const markedActual = /实际|真实|actual|history|historical/i.test(recordType);
      if (!markedForecast && (markedActual || timestamp <= anchorTimestamp)) return null;

      return normalizeForecastPoint({
        date,
        fixed_income: getCell(sheet, row, ['固定收入', '收入工资', 'fixed_income']),
        extra_income: getCell(sheet, row, ['额外收入', '收入其他', 'extra_income']),
        total_income: getCell(sheet, row, ['收入合计', '期间收入', 'total_income']),
        planned_spend: getCell(sheet, row, ['预测/实际支出', '预测支出', '期间支出', 'planned_spend']),
        net_cash_flow: getCell(sheet, row, ['净现金流', 'net_cash_flow']),
        projected_balance: getCell(sheet, row, [
          '实际/预测期末现金+股票',
          '预测期末现金+股票',
          '现金及现金等价物+股票',
          'projected_balance',
        ]),
      });
    })
    .filter(Boolean)
    .sort((left, right) => left.timestamp - right.timestamp);
}

function pickFirstNumber(points, key) {
  const item = points.find((point) => point[key] !== null);
  return item ? pointValue(item, key) : null;
}

function pickLastNumber(points, key) {
  const item = [...points].reverse().find((point) => point[key] !== null);
  return item ? pointValue(item, key) : null;
}

function pointValue(point, key) {
  return point?.[key] ?? null;
}

function buildForecastSection(payload, sheet, anchorTimestamp) {
  const payloadForecastPoints = Array.isArray(payload?.forecast_points)
    ? payload.forecast_points
    : Array.isArray(payload?.forecastPoints)
      ? payload.forecastPoints
      : [];

  const points = payloadForecastPoints
    .map(normalizeForecastPoint)
    .filter(Boolean)
    .sort((left, right) => left.timestamp - right.timestamp);

  const resolvedPoints = points.length ? points : buildSheetForecastPoints(sheet, anchorTimestamp);
  const firstPoint = resolvedPoints[0] || null;
  const lastPoint = resolvedPoints.at(-1) || null;

  return {
    points: resolvedPoints,
    monthCount: resolvedPoints.length,
    monthlyFixedIncome: pickFirstNumber(resolvedPoints, 'fixedIncome'),
    monthlyExtraIncome: pickFirstNumber(resolvedPoints, 'extraIncome'),
    monthlyTotalIncome: pickFirstNumber(resolvedPoints, 'totalIncome'),
    monthlyPlannedSpend: pickFirstNumber(resolvedPoints, 'plannedSpend'),
    monthlyNetCashFlow: pickFirstNumber(resolvedPoints, 'netCashFlow'),
    latestProjectedBalance: pickLastNumber(resolvedPoints, 'projectedBalance'),
    startDate: firstPoint?.date ?? '--',
    endDate: lastPoint?.date ?? '--',
  };
}

export function buildExpenseSheetViewModel(payload = {}, options = {}) {
  const resolvedPayload = payload ?? {};
  const sheets = resolvedPayload.sheets || [];
  const anchorTimestamp = resolveAnchorTimestamp(resolvedPayload, options);

  const expenseSheet = findSheet(sheets, EXPENSE_SHEET_NAMES);
  const budgetSheet = findSheet(sheets, BUDGET_SHEET_NAMES);
  const assetSheet = findSheet(sheets, ASSET_SHEET_NAMES);
  const socialSheet = findSheet(sheets, SOCIAL_SHEET_NAMES);

  const trendChart = buildTrendChartSection(resolvedPayload, expenseSheet, resolvedPayload.summary, anchorTimestamp);
  const forecast = buildForecastSection(resolvedPayload, expenseSheet, anchorTimestamp);
  const dailyAverage =
    trendChart.summary.latestDailyAverage ?? toNumber(resolvedPayload.summary?.time_cost?.daily_average);
  const cashAndStock =
    trendChart.summary.latestBalance ?? toNumber(resolvedPayload.summary?.assets?.cash_and_stock?.value);
  const monthlyRequired = toNumber(resolvedPayload.summary?.budget?.monthly_required);
  const coverageDays =
    trendChart.summary.coverageDays ?? (
      cashAndStock !== null && dailyAverage !== null && dailyAverage > 0
      ? roundMetric(cashAndStock / dailyAverage)
      : null
    );

  return {
    meta: {
      fileName: compactFileName(resolvedPayload.source?.path),
      fullPath: resolvedPayload.source?.path ?? '',
      updatedAt: resolvedPayload.source?.updated_at ?? '--',
      sheetCount: resolvedPayload.source?.sheet_count ?? sheets.length,
    },
    kpis: [
      { id: 'cashAndStock', label: '现金及等价物', value: cashAndStock, unit: 'currency' },
      { id: 'dailyBurn', label: '最近日均支出', value: dailyAverage, unit: 'currency' },
      { id: 'requiredBudget', label: '每月必须预算', value: monthlyRequired, unit: 'currency' },
      { id: 'coverageDays', label: '现金覆盖天数', value: coverageDays, unit: 'days' },
    ],
    trendChart,
    forecast,
    recentSpending: buildRecentSpending(expenseSheet, anchorTimestamp),
    budget: buildBudgetSection(budgetSheet, resolvedPayload.summary?.budget),
    assets: buildAssetSection(assetSheet),
    socialEvents: buildSocialEvents(socialSheet),
    rawSheets: sheets,
    defaultRawSheetName: expenseSheet?.name ?? sheets[0]?.name ?? '',
  };
}
