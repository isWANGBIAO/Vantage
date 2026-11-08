import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const component = readFileSync(new URL('./SleepAverageChart.jsx', import.meta.url), 'utf8');
const plots = readFileSync(new URL('./Plots.jsx', import.meta.url), 'utf8');
const registration = readFileSync(new URL('../utils/echarts.js', import.meta.url), 'utf8');
const styles = readFileSync(new URL('./SleepAverageChart.css', import.meta.url), 'utf8');

test('four sleep modes use one chart and canonical persisted settings', () => {
  assert.match(component, /const MODES = \['total', 'segments', 'monthly', 'rolling'\]/);
  assert.match(component, /loadSettingsState\(\)/);
  assert.match(component, /saveSettingsState\(\{ sleepChartMode: nextMode \}\)/);
  assert.match(component, /useState\('segments'\)/);
  assert.equal((component.match(/<ReactECharts\b/g) || []).length, 1);
  assert.ok(!component.includes('localStorage'));
  assert.match(plots, /chart\?\.id === 'sleep-schedule' \? \(\s*<SleepAverageChart/);
});

test('sleep preference reads cannot overwrite newer input and failed saves restore prior mode', () => {
  assert.match(component, /if \(!active\) return/);
  assert.match(component, /savePendingRef\.current/);
  assert.match(component, /setMode\(previous\)/);
  assert.match(component, /disabled=\{!loaded \|\| saving\}/);
  assert.match(component, /kind: 'readError'/);
  assert.match(component, /kind: 'saveError'/);
});

test('sleep chart snapshots the current zoom before mode changes', () => {
  assert.match(component, /datazoom: captureZoom/);
  assert.match(component, /captureZoom\(\);\s*const previous = mode/);
  assert.match(component, /start: saved.start, end: saved.end/);
});

test('bundled ECharts includes custom monthly segments and historical reference lines', () => {
  assert.match(registration, /MarkLineComponent/);
  assert.match(registration, /CustomChart/);
});

test('sleep chart grid can shrink below the old canvas intrinsic width', () => {
  assert.match(styles, /\.sleep-average-chart\{[^}]*grid-template-columns:minmax\(0,1fr\)/);
});

test('calendar grouping follows native visible bounds without persisting derived zoom state', () => {
  assert.match(component, /selectSleepAverageGranularity\(baseOption, groupingZoom\)/);
  assert.match(component, /zoomSourceRef\.current === baseOption/);
  assert.match(component, /startValue: item.startValue, endValue: item.endValue/);
  assert.match(component, /if \(next !== granularityRef\.current\)/);
  assert.match(component, /buildSleepAverageOption\(baseOption, mode, language, granularity\)/);
  assert.match(component, /data-granularity=\{granularity\}/);
  assert.match(component, /segments: '分段平均', monthly: '平均折线'/);
  assert.match(component, /mode === 'segments' \|\| mode === 'monthly'/);
  assert.ok(!component.includes('sleepChartGranularity'));
});
