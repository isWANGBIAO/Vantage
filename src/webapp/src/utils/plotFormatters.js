const PALETTE = ['#46a17d', '#4f7cff', '#f59f54', '#de96f5', '#f26d6d', '#57c5d9', '#d7c46f'];
const GRID_COLOR = 'rgba(15, 36, 29, 0.09)';
const AXIS_COLOR = 'rgba(19, 45, 37, 0.62)';
const TEXT_COLOR = '#10231c';
const POINTER_BG = '#183a2f';
const SURFACE_SHADOW = '0 24px 60px rgba(11, 27, 21, 0.12)';

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function trimZeros(value) {
  return value.replace(/\.0+$|(\.\d*[1-9])0+$/, '$1');
}

function formatNumber(value, precision = 1) {
  if (!isFiniteNumber(value)) {
    return '--';
  }

  if (Number.isInteger(value)) {
    return String(value);
  }

  return trimZeros(value.toFixed(precision));
}

function formatCurrency(value) {
  if (!isFiniteNumber(value)) {
    return '--';
  }

  return `¥${formatNumber(value, Math.abs(value) >= 100 ? 0 : 1)}`;
}

function formatDays(value) {
  if (!isFiniteNumber(value)) {
    return '--';
  }

  return `${formatNumber(value, 1)} 天`;
}

function formatDurationHours(value) {
  if (!isFiniteNumber(value)) {
    return '--';
  }

  const totalMinutes = Math.round(value * 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = Math.abs(totalMinutes % 60);

  if (hours > 0 && minutes > 0) {
    return `${hours}小时${minutes}分`;
  }

  if (hours > 0) {
    return `${hours}小时`;
  }

  return `${minutes}分钟`;
}

function formatPace(value) {
  if (!isFiniteNumber(value)) {
    return '--';
  }

  const totalSeconds = Math.round(value * 60);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.abs(totalSeconds % 60);

  return `${minutes}:${String(seconds).padStart(2, '0')} /km`;
}

function formatBySeriesName(seriesName, value) {
  const normalized = String(seriesName || '').toLowerCase();

  if (normalized.includes('体脂') || normalized.includes('body fat')) {
    return `${formatNumber(value, 1)}%`;
  }

  if (normalized.includes('体重') || normalized.includes('weight')) {
    return `${formatNumber(value, 1)} kg`;
  }

  if (normalized.includes('配速') || normalized.includes('pace')) {
    return formatPace(value);
  }

  if (normalized.includes('距离') || normalized.includes('distance')) {
    return `${formatNumber(value, 2)} km`;
  }

  if (normalized.includes('hrc')) {
    return `${formatNumber(value, 3)} m/beat`;
  }

  if (normalized.includes('speed')) {
    return `${formatNumber(value, 1)} m/min`;
  }

  if (normalized.includes('duration')) {
    return `${formatNumber(value, 1)} min`;
  }

  if (normalized.includes('cadence')) {
    return `${formatNumber(value, 0)} spm`;
  }

  if (normalized.includes('stride')) {
    return `${formatNumber(value, 2)} m`;
  }

  if (normalized.includes('心率') || normalized.includes('heart')) {
    return `${formatNumber(value, 0)} bpm`;
  }

  if (
    normalized.includes('余额') ||
    normalized.includes('收入') ||
    normalized.includes('支出') ||
    normalized.includes('balance') ||
    normalized.includes('expense') ||
    normalized.includes('income')
  ) {
    return formatCurrency(value);
  }

  if (normalized.includes('间隔') || normalized.includes('频率') || normalized.includes('周期')) {
    return formatDays(value);
  }

  if (
    normalized.includes('睡眠') ||
    normalized.includes('屏幕') ||
    normalized.includes('剩余') ||
    normalized.includes('时长') ||
    normalized.includes('hour')
  ) {
    return formatDurationHours(value);
  }

  return formatNumber(value, 2);
}

function tooltipHeader(point) {
  return point?.axisValueLabel || point?.name || point?.value?.[0] || '';
}

function buildTooltipRows(params, formatter) {
  return params
    .map((param) => {
      const marker = param.marker || '•';
      const seriesName = param.seriesName || '';
      const rawValue = Array.isArray(param.value) ? param.value[param.value.length - 1] : param.value;
      const value = formatter(seriesName, rawValue);
      return `${marker} ${seriesName}：${value}`;
    })
    .join('<br/>');
}

function genericTooltipFormatter(params) {
  const points = Array.isArray(params) ? params : [params];
  if (!points.length) {
    return '';
  }

  const header = tooltipHeader(points[0]);
  const rows = buildTooltipRows(points, formatBySeriesName);
  return header ? `${header}<br/>${rows}` : rows;
}

function weightBodyfatFormatter(params) {
  const points = Array.isArray(params) ? params : [params];
  if (!points.length) {
    return '';
  }

  const header = tooltipHeader(points[0]);
  const rows = buildTooltipRows(points, (seriesName, value) => {
    if (String(seriesName).includes('体脂')) {
      return `${formatNumber(value, 1)}%`;
    }

    return `${formatNumber(value, 1)} kg`;
  });

  return `${header}<br/>${rows}`;
}

function runningFormatter(params) {
  const points = Array.isArray(params) ? params : [params];
  if (!points.length) {
    return '';
  }

  const header = tooltipHeader(points[0]);
  const rows = buildTooltipRows(points, (seriesName, value) => {
    if (String(seriesName).includes('配速')) {
      return formatPace(value);
    }

    if (String(seriesName).includes('距离')) {
      return `${formatNumber(value, 2)} km`;
    }

    if (String(seriesName).includes('心率')) {
      return `${formatNumber(value, 0)} bpm`;
    }

    return formatNumber(value, 2);
  });

  return `${header}<br/>${rows}`;
}

function radarFormatter(params) {
  const points = Array.isArray(params) ? params : [params];
  if (!points.length) {
    return '';
  }

  const point = points[0];
  const labels = Array.isArray(point?.dimensionNames) ? point.dimensionNames : [];
  const values = Array.isArray(point?.value) ? point.value : [];
  const rows = labels.map((label, index) => `${label}：${formatNumber(values[index], 1)}`).join('<br/>');

  return `${point.seriesName || '目标雷达'}<br/>${rows}`;
}

function createTooltipFormatter(chartId) {
  switch (chartId) {
    case 'weight-bodyfat':
      return weightBodyfatFormatter;
    case 'running':
      return runningFormatter;
    case 'radar-goal':
      return radarFormatter;
    default:
      return genericTooltipFormatter;
  }
}

function mergeAxis(axis, fallbackType = 'value') {
  if (Array.isArray(axis)) {
    return axis.map((item) => mergeAxis(item, fallbackType));
  }

  const input = axis || {};
  const axisLine = input.axisLine || {};
  const axisTick = input.axisTick || {};
  const axisLabel = input.axisLabel || {};
  const splitLine = input.splitLine || {};
  const splitArea = input.splitArea || {};
  const axisPointer = input.axisPointer || {};
  const nameTextStyle = input.nameTextStyle || {};
  const type = input.type || fallbackType;

  return {
    ...input,
    type,
    axisLine: {
      show: false,
      ...axisLine,
    },
    axisTick: {
      show: false,
      ...axisTick,
    },
    axisLabel: {
      color: AXIS_COLOR,
      fontSize: 11,
      margin: 12,
      hideOverlap: true,
      ...axisLabel,
    },
    splitLine: {
      show: type === 'value',
      ...splitLine,
      lineStyle: {
        color: GRID_COLOR,
        width: 1,
        type: 'dashed',
        ...(splitLine.lineStyle || {}),
      },
    },
    splitArea: {
      show: false,
      ...splitArea,
    },
    axisPointer: {
      ...axisPointer,
      label: {
        color: '#f3f7f5',
        backgroundColor: POINTER_BG,
        padding: [6, 8],
        borderRadius: 8,
        ...(axisPointer.label || {}),
      },
      lineStyle: {
        color: 'rgba(24, 58, 47, 0.18)',
        width: 1,
        ...(axisPointer.lineStyle || {}),
      },
    },
    nameTextStyle: {
      color: AXIS_COLOR,
      fontSize: 11,
      ...nameTextStyle,
    },
  };
}

function mergeLegend(legend) {
  if (Array.isArray(legend)) {
    return legend.map((item) => mergeLegend(item));
  }

  const input = legend || {};
  const textStyle = input.textStyle || {};

  return {
    icon: 'roundRect',
    itemWidth: 10,
    itemHeight: 10,
    itemGap: 18,
    top: 10,
    ...input,
    textStyle: {
      color: AXIS_COLOR,
      fontSize: 11,
      ...textStyle,
    },
  };
}

function mergeGrid(grid) {
  if (Array.isArray(grid)) {
    return grid.map((item) => mergeGrid(item));
  }

  return {
    top: 74,
    right: 28,
    bottom: 54,
    left: 58,
    containLabel: false,
    ...(grid || {}),
  };
}

function mergeDataZoom(dataZoom) {
  if (!dataZoom) {
    return undefined;
  }

  const list = Array.isArray(dataZoom) ? dataZoom : [dataZoom];
  return list.map((item) => {
    const handleStyle = item.handleStyle || {};
    const textStyle = item.textStyle || {};
    const dataBackground = item.dataBackground || {};
    const fillerColor = item.fillerColor || 'rgba(70, 161, 125, 0.14)';

    return {
      ...item,
      borderColor: 'rgba(15, 36, 29, 0.1)',
      backgroundColor: 'rgba(12, 29, 23, 0.03)',
      fillerColor,
      handleIcon:
        'path://M8.2,13.1V2.9h1.6v10.2H8.2z M14.2,13.1V2.9h1.6v10.2H14.2z',
      handleSize: '90%',
      handleStyle: {
        color: '#edf3ef',
        borderColor: 'rgba(15, 36, 29, 0.18)',
        shadowBlur: 10,
        shadowColor: 'rgba(12, 27, 21, 0.12)',
        ...handleStyle,
      },
      textStyle: {
        color: AXIS_COLOR,
        ...textStyle,
      },
      dataBackground: {
        ...dataBackground,
        lineStyle: {
          color: 'rgba(15, 36, 29, 0.18)',
          ...(dataBackground.lineStyle || {}),
        },
        areaStyle: {
          color: 'rgba(15, 36, 29, 0.06)',
          ...(dataBackground.areaStyle || {}),
        },
      },
    };
  });
}

function mergeSeries(series, chartId) {
  if (!Array.isArray(series)) {
    return [];
  }

  return series.map((item) => {
    const input = item || {};
    const type = input.type || 'line';
    const lineStyle = input.lineStyle || {};
    const itemStyle = input.itemStyle || {};
    const areaStyle = input.areaStyle || {};
    const emphasis = input.emphasis || {};

    if (type === 'bar') {
      return {
        ...input,
        barMaxWidth: input.barMaxWidth || 32,
        itemStyle: {
          borderRadius: [10, 10, 3, 3],
          ...itemStyle,
        },
        emphasis: {
          focus: 'series',
          ...emphasis,
        },
      };
    }

    if (type === 'scatter') {
      return {
        ...input,
        symbolSize: input.symbolSize || 10,
        itemStyle: {
          opacity: itemStyle.opacity ?? 0.9,
          borderWidth: itemStyle.borderWidth ?? 1,
          borderColor: itemStyle.borderColor || 'rgba(255, 255, 255, 0.8)',
          ...itemStyle,
        },
        emphasis: {
          focus: 'series',
          scale: true,
          ...emphasis,
        },
      };
    }

    if (type === 'radar') {
      return {
        ...input,
        symbol: input.symbol || 'circle',
        symbolSize: input.symbolSize || 7,
        lineStyle: {
          width: 2,
          ...lineStyle,
        },
        areaStyle: {
          opacity: areaStyle.opacity ?? 0.12,
          ...areaStyle,
        },
      };
    }

    return {
      ...input,
      smooth: input.smooth ?? true,
      showSymbol: input.showSymbol ?? false,
      symbol: input.symbol || 'circle',
      symbolSize: input.symbolSize || 6,
      lineStyle: {
        width: 3,
        cap: 'round',
        join: 'round',
        shadowBlur: 10,
        shadowColor: 'rgba(33, 71, 60, 0.1)',
        ...lineStyle,
      },
      itemStyle: {
        borderWidth: itemStyle.borderWidth ?? 1,
        borderColor: itemStyle.borderColor || 'rgba(255, 255, 255, 0.9)',
        ...itemStyle,
      },
      areaStyle:
        chartId === 'weight-bodyfat' || chartId === 'balance'
          ? {
              opacity: areaStyle.opacity ?? 0.06,
              ...areaStyle,
            }
          : input.areaStyle,
      emphasis: {
        focus: 'series',
        ...emphasis,
      },
    };
  });
}

export function formatSummaryValue(summary) {
  if (summary == null) {
    return '--';
  }

  if (typeof summary === 'string') {
    return summary;
  }

  if (typeof summary === 'number') {
    return formatNumber(summary, 1);
  }

  if (summary.text) {
    return summary.text;
  }

  const value = summary.value;
  const unit = summary.unit || summary.suffix || '';
  const precision = summary.precision ?? 1;
  const type = summary.type || '';

  if (value == null || value === '') {
    return '--';
  }

  if (type === 'currency' || unit === '¥' || unit === '元') {
    return formatCurrency(Number(value));
  }

  if (type === 'days' || unit === '天') {
    return formatDays(Number(value));
  }

  if (type === 'duration' || unit === '小时') {
    return formatDurationHours(Number(value));
  }

  if (type === 'pace') {
    return formatPace(Number(value));
  }

  if (typeof value === 'number') {
    const formatted = formatNumber(value, precision);
    return unit ? `${formatted} ${unit}` : formatted;
  }

  return unit ? `${value} ${unit}` : String(value);
}

export function buildChartOption(chart) {
  const source = chart?.option || {};
  const tooltip = source.tooltip || {};

  return {
    ...source,
    backgroundColor: 'transparent',
    color: source.color || PALETTE,
    animationDuration: source.animationDuration ?? 650,
    animationEasing: source.animationEasing || 'cubicOut',
    textStyle: {
      color: TEXT_COLOR,
      ...(source.textStyle || {}),
    },
    grid: mergeGrid(source.grid),
    legend: mergeLegend(source.legend),
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(9, 22, 17, 0.92)',
      borderWidth: 0,
      padding: [12, 14],
      textStyle: {
        color: '#f5faf7',
        fontSize: 12,
      },
      extraCssText: `box-shadow: ${SURFACE_SHADOW}; border-radius: 16px;`,
      axisPointer: {
        type: 'line',
      },
      ...tooltip,
      formatter: createTooltipFormatter(chart?.id),
    },
    xAxis: mergeAxis(source.xAxis, 'category'),
    yAxis: mergeAxis(source.yAxis, 'value'),
    radar: source.radar
      ? {
          ...source.radar,
          axisName: {
            color: TEXT_COLOR,
            fontSize: 11,
            ...(source.radar.axisName || {}),
          },
          splitLine: {
            lineStyle: {
              color: 'rgba(15, 36, 29, 0.08)',
              ...(source.radar.splitLine?.lineStyle || {}),
            },
            ...(source.radar.splitLine || {}),
          },
          splitArea: {
            areaStyle: {
              color: ['rgba(70, 161, 125, 0.02)', 'rgba(70, 161, 125, 0.05)'],
              ...(source.radar.splitArea?.areaStyle || {}),
            },
            ...(source.radar.splitArea || {}),
          },
        }
      : source.radar,
    dataZoom: mergeDataZoom(source.dataZoom),
    series: mergeSeries(source.series, chart?.id),
  };
}
