const numberFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 0,
});

function cloneOption(option) {
  return JSON.parse(JSON.stringify(option ?? {}));
}

function formatHours(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return `${Number(value).toFixed(2)} h`;
}

function formatHoursDelta(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const numeric = Number(value);
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)} h`;
}

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return `${Number(value).toFixed(1)} %`;
}

function formatCurrency(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return `¥${integerFormatter.format(Number(value))}`;
}

function formatCount(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return integerFormatter.format(Number(value));
}

function formatDays(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return `${Number(value).toFixed(1)} 天`;
}

function formatDistance(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return `${Number(value).toFixed(2)} km`;
}

function formatPace(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const numeric = Number(value);
  const minutes = Math.floor(numeric);
  let seconds = Math.round((numeric - minutes) * 60);
  let adjustedMinutes = minutes;
  if (seconds === 60) {
    adjustedMinutes += 1;
    seconds = 0;
  }
  return `${adjustedMinutes}:${String(seconds).padStart(2, '0')}/km`;
}

function buildAxisTooltipFormatter(formatValue) {
  return (params) => {
    if (!params || params.length === 0) return '';
    const [first] = params;
    const label = first.axisValueLabel ?? first.axisValue ?? '';
    const lines = [`<div style="margin-bottom:6px;font-weight:600;">${label}</div>`];
    params.forEach((item) => {
      const value = Array.isArray(item.value) ? item.value[item.value.length - 1] : item.value;
      lines.push(
        `${item.marker}${item.seriesName}<span style="float:right;margin-left:12px;font-weight:600;">${formatValue(item.seriesName, value)}</span>`,
      );
    });
    return lines.join('<br/>');
  };
}

function weightBodyfatFormatter(seriesName, value) {
  if (seriesName.includes('体脂')) return formatPercent(value);
  return value == null ? '--' : `${Number(value).toFixed(2)} kg`;
}

function runningFormatter(seriesName, value) {
  if (seriesName.includes('配速')) return formatPace(value);
  if (seriesName.includes('距离')) return formatDistance(value);
  if (seriesName.includes('心率')) return `${formatCount(value)} bpm`;
  return numberFormatter.format(Number(value));
}

export function buildChartOption(chart) {
  const option = cloneOption(chart?.option);
  option.animationDuration = 450;
  option.textStyle = {
    color: '#d7deeb',
    ...(option.textStyle ?? {}),
  };
  option.toolbox = {
    right: 12,
    ...(option.toolbox ?? {}),
    feature: {
      saveAsImage: { pixelRatio: 2, ...(option.toolbox?.feature?.saveAsImage ?? {}) },
      ...(option.toolbox?.feature ?? {}),
    },
  };
  option.grid = {
    top: 72,
    left: 56,
    right: 32,
    bottom: 72,
    containLabel: true,
    ...(option.grid ?? {}),
  };

  const yAxes = Array.isArray(option.yAxis) ? option.yAxis : option.yAxis ? [option.yAxis] : [];
  const xAxes = Array.isArray(option.xAxis) ? option.xAxis : option.xAxis ? [option.xAxis] : [];

  xAxes.forEach((axis) => {
    axis.axisLabel = {
      color: '#8ea0b8',
      ...(axis.axisLabel ?? {}),
    };
    axis.axisLine = {
      lineStyle: { color: 'rgba(255,255,255,0.18)' },
      ...(axis.axisLine ?? {}),
    };
    axis.splitLine = axis.splitLine ?? { show: false };
  });

  yAxes.forEach((axis) => {
    axis.axisLabel = {
      color: '#8ea0b8',
      ...(axis.axisLabel ?? {}),
    };
    axis.axisLine = {
      lineStyle: { color: 'rgba(255,255,255,0.18)' },
      ...(axis.axisLine ?? {}),
    };
    axis.splitLine = {
      lineStyle: { color: 'rgba(255,255,255,0.08)' },
      ...(axis.splitLine ?? {}),
    };
  });

  option.legend = {
    textStyle: { color: '#d7deeb' },
    ...(option.legend ?? {}),
  };

  switch (chart?.formatter) {
    case 'weight-bodyfat':
      if (yAxes[0]) yAxes[0].axisLabel.formatter = (value) => `${Number(value).toFixed(1)} kg`;
      if (yAxes[1]) yAxes[1].axisLabel.formatter = (value) => `${Number(value).toFixed(0)} %`;
      if (yAxes[2]) yAxes[2].axisLabel.formatter = (value) => `${Number(value).toFixed(1)} kg`;
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter(weightBodyfatFormatter),
      };
      break;
    case 'hours':
      yAxes.forEach((axis) => {
        axis.axisLabel.formatter = (value) => `${Number(value).toFixed(1)} h`;
      });
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter((_seriesName, value) => formatHours(value)),
      };
      break;
    case 'hours-delta':
      yAxes.forEach((axis) => {
        axis.axisLabel.formatter = (value) => formatHoursDelta(value);
      });
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter((_seriesName, value) => formatHoursDelta(value)),
      };
      break;
    case 'percent':
      yAxes.forEach((axis) => {
        axis.axisLabel.formatter = (value) => `${Number(value).toFixed(0)} %`;
      });
      option.tooltip = {
        ...(option.tooltip ?? {}),
        valueFormatter: (value) => formatPercent(value),
      };
      break;
    case 'count':
      yAxes.forEach((axis) => {
        axis.axisLabel.formatter = (value) => formatCount(value);
      });
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter((_seriesName, value) => formatCount(value)),
      };
      break;
    case 'days':
      yAxes.forEach((axis) => {
        axis.axisLabel.formatter = (value) => formatDays(value);
      });
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter((_seriesName, value) => formatDays(value)),
      };
      break;
    case 'currency':
      if (yAxes[0]) yAxes[0].axisLabel.formatter = (value) => formatCurrency(value);
      if (yAxes[1]) yAxes[1].axisLabel.formatter = (value) => formatCurrency(value);
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter((_seriesName, value) => formatCurrency(value)),
      };
      break;
    case 'running':
      if (yAxes[0]) yAxes[0].axisLabel.formatter = (value) => formatPace(value);
      if (yAxes[1]) yAxes[1].axisLabel.formatter = (value) => formatDistance(value);
      if (yAxes[2]) yAxes[2].axisLabel.formatter = (value) => `${formatCount(value)} bpm`;
      option.tooltip = {
        trigger: 'axis',
        ...(option.tooltip ?? {}),
        formatter: buildAxisTooltipFormatter(runningFormatter),
      };
      break;
    default:
      option.tooltip = option.tooltip ?? { trigger: 'axis' };
      break;
  }

  return option;
}

export function formatSummaryValue(summary) {
  return summary?.value ?? '--';
}
