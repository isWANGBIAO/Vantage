import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from '../utils/echarts.js';
import { buildSleepAverageOption } from '../utils/sleepAverageOptions.js';
import { loadSettingsState, saveSettingsState } from '../utils/settingsState.js';
import { redactSensitiveText } from '../utils/sensitiveText';
import './SleepAverageChart.css';

const MODES = ['total', 'segments', 'monthly', 'rolling'];
const COPY = {
  zh: {
    label: '显示方式', total: '历史平均', segments: '月均横线', monthly: '月均折线', rolling: '30日趋势',
    loading: '正在读取图表偏好…', saving: '正在保存…', retry: '重试读取',
    readError: '图表偏好读取失败，尚未更改设置。', saveError: '保存失败，已恢复上次选择。',
    note: '每日记录一直保留；虚线为全部历史平均。月均至少7天，30日平均至少15天；缺失数据不补零，未完整月份使用虚线。',
  },
  en: {
    label: 'Display mode', total: 'Historical mean', segments: 'Monthly segments', monthly: 'Monthly line', rolling: '30-day trend',
    loading: 'Loading chart preference…', saving: 'Saving…', retry: 'Retry loading',
    readError: 'Could not load the chart preference. Settings have not changed.', saveError: 'Save failed. The previous choice was restored.',
    note: 'Daily records remain visible; dashed references use all history. Monthly means need 7 days, trailing 30-day means need 15. Missing data stays missing; incomplete months are dashed.',
  },
};

export default function SleepAverageChart({ baseOption, language, themeTokens, height }) {
  const copy = COPY[String(language).toLowerCase().startsWith('en') ? 'en' : 'zh'];
  const [mode, setMode] = useState('segments');
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState(null);
  const [readAttempt, setReadAttempt] = useState(0);
  const chartRef = useRef(null);
  const zoomRef = useRef(null);
  const mountedRef = useRef(false);
  const savePendingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    let active = true;
    loadSettingsState().then((state) => {
      if (!active) return;
      const value = state.settings?.sleepChartMode;
      setMode(MODES.includes(value) ? value : 'segments');
      setFailure(null);
      setLoaded(true);
    }).catch((error) => {
      if (active) setFailure({ kind: 'readError', detail: redactSensitiveText(String(error.message || '')) });
    });
    return () => { active = false; };
  }, [readAttempt]);

  const captureZoom = useCallback(() => {
    const zoom = chartRef.current?.getEchartsInstance().getOption().dataZoom;
    if (!Array.isArray(zoom)) return;
    zoomRef.current = zoom.map((item) => ({ start: item.start, end: item.end }));
  }, []);
  const events = useMemo(() => ({ datazoom: captureZoom }), [captureZoom]);
  const option = useMemo(() => {
    const next = buildSleepAverageOption(baseOption, mode, language);
    if (!zoomRef.current || !Array.isArray(next.dataZoom)) return next;
    return { ...next, dataZoom: next.dataZoom.map((item, index) => {
      const saved = zoomRef.current[index] || zoomRef.current[0];
      if (!saved || !Number.isFinite(saved.start) || !Number.isFinite(saved.end)) return item;
      const { startValue: _startValue, endValue: _endValue, ...rest } = item;
      return { ...rest, start: saved.start, end: saved.end };
    }) };
  }, [baseOption, mode, language]);

  const selectMode = async (nextMode) => {
    if (!loaded || savePendingRef.current || nextMode === mode) return;
    captureZoom();
    const previous = mode;
    savePendingRef.current = true;
    setSaving(true);
    setFailure(null);
    setMode(nextMode);
    try {
      const state = await saveSettingsState({ sleepChartMode: nextMode });
      if (mountedRef.current) {
        const saved = state.settings?.sleepChartMode;
        if (!MODES.includes(saved)) throw new Error('Invalid saved chart preference');
        setMode(saved);
      }
    } catch (error) {
      if (mountedRef.current) {
        setMode(previous);
        setFailure({ kind: 'saveError', detail: redactSensitiveText(String(error.message || '')) });
      }
    } finally {
      savePendingRef.current = false;
      if (mountedRef.current) setSaving(false);
    }
  };

  return (
    <div className="sleep-average-chart" data-mode={mode} data-zoom-start={option.dataZoom?.[0]?.start}
      data-zoom-end={option.dataZoom?.[0]?.end} style={{ '--sleep-control-bg': themeTokens.navChipBackground,
      '--sleep-control-text': themeTokens.cardText, '--sleep-control-active-bg': themeTokens.refreshButtonBackground,
      '--sleep-control-active-text': themeTokens.refreshButtonText, '--sleep-control-border': themeTokens.cardBorder }}>
      <div className="sleep-average-modes" role="group" aria-label={copy.label}>
        {MODES.map((value) => <button key={value} type="button" data-sleep-mode={value}
          aria-pressed={mode === value} disabled={!loaded || saving} onClick={() => selectMode(value)}>{copy[value]}</button>)}
      </div>
      <ReactECharts ref={chartRef} option={option} notMerge lazyUpdate onEvents={events}
        style={{ width: '100%', height }} />
      <div className="sleep-average-status" role="status">
        {failure ? <><span>{copy[failure.kind]} {failure.detail}</span>{failure.kind === 'readError' ? <button type="button"
          onClick={() => { setFailure(null); setReadAttempt((value) => value + 1); }}>{copy.retry}</button> : null}</>
          : !loaded ? copy.loading : saving ? copy.saving : copy.note}
      </div>
    </div>
  );
}
