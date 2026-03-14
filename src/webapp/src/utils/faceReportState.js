const TREND_VIEW_LABELS = {
  day: '最近24小时',
  week: '最近7天',
  month: '最近30天',
  all: '全部历史',
};

function normalizeTrendViews(trendViews) {
  const normalized = {};

  for (const [key, label] of Object.entries(TREND_VIEW_LABELS)) {
    const view = trendViews?.[key];
    normalized[key] = {
      label: view?.label || label,
      points: Array.isArray(view?.points) ? view.points : [],
    };
  }

  return normalized;
}

export function getFaceReportState(payload) {
  if (!payload) {
    return {
      status: 'empty',
      data: null,
      error: null,
    };
  }

  if (payload.error === 'No report generated') {
    return {
      status: 'empty',
      data: null,
      error: null,
    };
  }

  if (payload.error) {
    return {
      status: 'error',
      data: null,
      error: payload.error,
    };
  }

  return {
    status: 'ready',
    data: {
      ...payload,
      trend_views: normalizeTrendViews(payload.trend_views),
    },
    error: null,
  };
}
