import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  buildSleepScheduleGeometry, formatSleepClock, nearestSleepRecord, prepareSleepScheduleView,
} from '../utils/sleepSchedule.js';
import './SleepScheduleChart.css';

const COPY = {
  zh: {
    eyebrow: '健康 · 睡眠', title: '作息趋势', subtitle: '每天看淡线，每周看横段，早晚变化看箭头。',
    range: '查看时间范围', month: '月', quarter: '3个月', half: '6个月', current: '最新记录周的典型作息',
    bedtime: '入睡', wake: '起床', missing: '记录不足', baseline: '基准周', daily: '淡细线：每天',
    weekly: '粗横线：每7天', hint: '轻点图表，同时查看当天记录和该周的典型时间。',
    graph: '每日细线、每周阶梯横线和方向箭头。单位为相比基准的分钟数。左右方向键可查看每天记录。',
    earlier: '↓ 提前', later: '↑ 推迟', guide: '箭头表示相邻两周的变化', minutes: '分钟',
    footer: '周一至周日分组，取每周中位数；至少4天有效记录，不足时留空，不跨缺失周连线。',
    partialFooter: '未满一周使用短虚线；箭头只表示已发生的变化，不是预测。',
    noBaseline: '当前范围尚无有效作息记录，暂无法展示。',
    dayBaseline: '周记录不足，暂以首个有效日为基准',
  },
  en: {
    eyebrow: 'Health · Sleep', title: 'Sleep schedule', subtitle: 'Daily fine lines, weekly steps, and arrows for earlier or later times.',
    range: 'Date range', month: 'Month', quarter: '3 months', half: '6 months', current: 'Typical times in latest recorded week',
    bedtime: 'Bedtime', wake: 'Wake time', missing: 'Not enough data', baseline: 'Baseline week', daily: 'Fine lines: daily',
    weekly: 'Bold steps: weekly', hint: 'Select the chart to inspect the day and its weekly typical times.',
    graph: 'Daily lines, weekly steps and direction arrows. Minutes relative to the reference. Use Left and Right to inspect days.',
    earlier: '↓ Earlier', later: '↑ Later', guide: 'Arrows compare adjacent weeks', minutes: 'min',
    footer: 'Monday–Sunday medians require at least 4 distinct recorded days. Missing weeks remain gaps.',
    partialFooter: 'An incomplete week has a short dashed step. Arrows describe observed changes, not forecasts.',
    noBaseline: 'No valid sleep records are available in this range yet.',
    dayBaseline: 'Too few weekly records; temporarily using the first valid day as baseline',
  },
};

function weekChange(value, english) {
  if (!Number.isFinite(value)) return english ? 'Previous-week comparison unavailable' : '与上周相比：记录不足';
  if (value === 0) return english ? '↔ Same as last week' : '↔ 与上周基本一致';
  return english
    ? `${value < 0 ? '↓' : '↑'} ${Math.abs(value)} min ${value < 0 ? 'earlier' : 'later'} than last week`
    : `${value < 0 ? '↓ 较上周提前' : '↑ 较上周推迟'} ${Math.abs(value)} 分钟`;
}

const shortDate = (value) => value?.slice(5).replace('-', '/') || '';

export default function SleepScheduleChart({ chart, chartRef, theme = 'dark', language = 'zh-CN', warningContent = null }) {
  const english = String(language).toLowerCase().startsWith('en');
  const copy = COPY[english ? 'en' : 'zh'];
  const [rangeDays, setRangeDays] = useState(90);
  const [width, setWidth] = useState(600);
  const [selectedDate, setSelectedDate] = useState(null);
  const [announcedDate, setAnnouncedDate] = useState(null);
  const holderRef = useRef(null);
  const detailId = useId();
  const view = useMemo(() => prepareSleepScheduleView(chart?.sleep_schedule, rangeDays), [chart?.sleep_schedule, rangeDays]);
  const geometry = useMemo(() => buildSleepScheduleGeometry(view, width, width < 500 ? 305 : 340), [view, width]);
  const selection = useMemo(() => {
    const record = view?.daily.find((row) => row.date === selectedDate);
    if (!record) return null;
    return { record, week: view.weeks.find((week) => record.timestamp >= week.start_timestamp && record.timestamp <= week.end_timestamp) };
  }, [selectedDate, view]);

  useEffect(() => {
    const holder = holderRef.current;
    if (!holder) return undefined;
    const update = () => {
      const next = holder.getBoundingClientRect().width;
      if (next > 0) setWidth((previous) => Math.abs(previous - next) > 0.5 ? next : previous);
    };
    update();
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(update);
      observer.observe(holder);
      return () => observer.disconnect();
    }
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const clock = (value) => formatSleepClock(value) || copy.missing;
  const current = view?.current_week;
  const weekStatus = current
    ? english
      ? `${current.start}–${current.end} · ${current.partial ? 'Incomplete week' : 'Full calendar week'} · ${current.record_count} recorded days`
      : `${current.start}—${current.end} · ${current.partial ? '该周未满' : '完整日历周'} · ${current.record_count}天记录`
    : copy.missing;

  const inspect = (event, announce = false) => {
    if (!geometry) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left - geometry.left) / geometry.innerWidth;
    const result = nearestSleepRecord(view, ratio);
    if (result) {
      setSelectedDate(result.record.date);
      if (announce) setAnnouncedDate(result.record.date);
    }
  };
  const inspectKey = (event) => {
    if (!view?.daily.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = view.daily.findIndex((row) => row.date === selectedDate);
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? view.daily.length - 1
      : Math.max(0, Math.min(view.daily.length - 1, (index < 0 ? 0 : index) + (event.key === 'ArrowLeft' ? -1 : 1)));
    setSelectedDate(view.daily[target].date);
    setAnnouncedDate(view.daily[target].date);
  };
  let detail = copy.hint;
  if (selection) {
    const { record, week } = selection;
    detail = english
      ? `${record.date} · Day: ${clock(record.bedtime_hour)}–${clock(record.wake_hour)} · Week: ${clock(week?.bedtime_hour)}–${clock(week?.wake_hour)}`
      : `${record.date} 当天：${clock(record.bedtime_hour)}—${clock(record.wake_hour)} | 该周典型：${clock(week?.bedtime_hour)}—${clock(week?.wake_hour)}`;
  }
  const baseline = view?.baseline;
  const shade = selection?.week && geometry ? {
    x: geometry.x(selection.week.start_timestamp),
    width: geometry.x(selection.week.end_timestamp + 86_400_000) - geometry.x(selection.week.start_timestamp),
  } : null;

  return (
    <article ref={chartRef} id="plot-sleep-schedule" className="sleep-schedule-card" data-theme={theme === 'light' ? 'light' : 'dark'}>
      <header className="sleep-schedule-heading">
        <span>{copy.eyebrow}</span><h3>{copy.title}</h3><p>{copy.subtitle}</p>
      </header>
      <div className="sleep-schedule-ranges" role="group" aria-label={copy.range}>
        {[[30, copy.month], [90, copy.quarter], [180, copy.half]].map(([days, label]) => (
          <button key={days} type="button" aria-pressed={rangeDays === days} onClick={() => setRangeDays(days)}>{label}</button>
        ))}
      </div>
      {warningContent}
      <div className="sleep-schedule-surface">
        <div className="sleep-schedule-period"><strong>{copy.current}</strong><span>{weekStatus}</span></div>
        <div className="sleep-schedule-times">
          <div><span><i className="sleep-bedtime-dot" />{copy.bedtime}</span><strong>{clock(current?.bedtime_hour)}</strong><small>{weekChange(view?.bedtime_change, english)}</small></div>
          <div><span><i className="sleep-wake-dot" />{copy.wake}</span><strong>{clock(current?.wake_hour)}</strong><small>{weekChange(view?.wake_change, english)}</small></div>
        </div>
        <div className="sleep-schedule-baseline">{view?.baseline_kind === 'day' ? copy.dayBaseline : copy.baseline}: {baseline ? `${baseline.start} — ${baseline.end}` : copy.missing}</div>
        <div className="sleep-schedule-legend"><span><i className="sleep-schedule-daily-key" />{copy.daily}</span><span><i className="sleep-schedule-weekly-key" />{copy.weekly}</span></div>
        <div ref={holderRef} className="sleep-schedule-chart">
          {geometry ? (
            <svg width={geometry.width} height={geometry.height} role="img" aria-label={copy.graph} aria-describedby={detailId}
              tabIndex={0} onPointerMove={inspect} onClick={(event) => inspect(event, true)} onKeyDown={inspectKey}>
              <text x={geometry.left} y={10} className="sleep-schedule-axis">{copy.minutes}</text>
              {shade ? <rect x={shade.x} y={geometry.top} width={shade.width} height={geometry.height - geometry.top - geometry.bottom} className="sleep-schedule-shade" /> : null}
              {geometry.yTicks.map((tick) => (
                <g key={tick.value}>
                  <line x1={geometry.left} x2={geometry.width - geometry.right} y1={tick.y} y2={tick.y} className="sleep-schedule-grid" strokeDasharray={tick.value === 0 ? '3 4' : undefined} />
                  <text x={geometry.left - 9} y={tick.y + 4} textAnchor="end" className="sleep-schedule-axis">
                    {tick.value === 0 ? english ? '0' : '基准' : english ? `${tick.value > 0 ? '+' : ''}${tick.value}m` : `${tick.value > 0 ? '晚' : '早'}${Math.abs(tick.value)}分`}
                  </text>
                </g>
              ))}
              {geometry.xTicks.map((tick) => <text key={tick.date} x={tick.x} y={geometry.height - 10} textAnchor={tick.anchor} className="sleep-schedule-axis">{shortDate(tick.date)}</text>)}
              {geometry.dailyPaths.map((path) => <path key={path.key} d={path.path} data-series="daily" className={`sleep-schedule-daily sleep-series-${path.key}`} />)}
              {geometry.dailyPoints.map((point) => <circle key={`${point.key}-${point.date}`} cx={point.x} cy={point.y} r={3} data-series="daily-point" data-isolated="true" className={`sleep-schedule-daily-point sleep-series-${point.key}`} />)}
              {geometry.weekPaths.map((path) => <path key={`${path.key}-${path.start}`} d={path.path} data-series="weekly" className={`sleep-schedule-weekly sleep-series-${path.key}`} strokeDasharray={path.partial ? '3 5' : path.key === 'wake' ? '7 4' : undefined} />)}
              {geometry.arrows.map((arrow) => <path key={`${arrow.key}-${arrow.start}`} d={arrow.path} data-direction={arrow.direction} className={`sleep-schedule-arrow sleep-series-${arrow.key}`} />)}
            </svg>
          ) : <div className="sleep-schedule-unavailable" role="status">{copy.noBaseline}</div>}
        </div>
        <div id={detailId} className="sleep-schedule-detail">{detail}</div>
        <span className="sleep-schedule-announcement" aria-live="polite">{announcedDate !== null && announcedDate === selectedDate ? detail : ''}</span>
        <div className="sleep-schedule-guide"><span>{copy.earlier}</span><span>{copy.later}</span><span>{copy.guide}</span></div>
      </div>
      <footer>
        <span>{view ? `${new Date(view.start).toISOString().slice(0, 10)} — ${view.latest_date}` : ''}</span>
        <span>{copy.footer} {copy.partialFooter}</span>
        {view?.duplicate_day_count ? <span>{english ? `Source data: ${view.duplicate_day_count} duplicate dates consolidated using the last valid record.` : `源数据中${view.duplicate_day_count}个重复日期已按最后有效记录合并。`}</span> : null}
      </footer>
    </article>
  );
}
