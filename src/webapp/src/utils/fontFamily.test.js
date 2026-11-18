import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { getFontFamilies, withChartFont, CHINESE_FONT_FAMILIES } from './fontFamily.js';

test('Chinese fonts are explicit before all language-sensitive generic families', () => {
  for (const id of Object.keys(CHINESE_FONT_FAMILIES)) {
    const fonts = getFontFamilies(id);
    assert.ok(fonts.main.indexOf(CHINESE_FONT_FAMILIES[id]) < fonts.main.indexOf('system-ui'));
    assert.ok(fonts.mono.indexOf(CHINESE_FONT_FAMILIES[id]) < fonts.mono.indexOf('ui-monospace'));
  }
  assert.deepEqual(getFontFamilies('invalid'), getFontFamilies('microsoft-yahei'));
});

test('canvas and HTML chart tooltips use the selected font without mutating source data', () => {
  const option = { textStyle: { color: 'red' }, tooltip: { textStyle: { color: 'blue' } }, series: [] };
  const next = withChartFont(option, getFontFamilies().main);
  assert.equal(next.textStyle.fontFamily, getFontFamilies().main);
  assert.equal(next.tooltip.textStyle.fontFamily, getFontFamilies().main);
  assert.equal(next.tooltip.textStyle.color, 'blue');
  assert.equal(option.textStyle.fontFamily, undefined);
  assert.equal(Object.hasOwn(withChartFont({}, 'demo'), 'tooltip'), false);
  assert.equal(withChartFont({ tooltip: [{}] }, 'demo').tooltip[0].textStyle.fontFamily, 'demo');
});

test('font preference is hydrated from shared settings and applied to CSS and chart context', () => {
  const app = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../index.css', import.meta.url), 'utf8');
  const chart = readFileSync(new URL('./echarts.js', import.meta.url), 'utf8');
  assert.match(app, /nextState.settings\?\.chineseFontFamily/);
  assert.match(app, /FontFamilyContext.Provider value=\{fontFamilies\}/);
  assert.match(app, /setProperty\('--font-main', fontFamilies.main\)/);
  assert.match(css, /--font-main:[^;]*Microsoft YaHei[^;]*system-ui/);
  assert.match(css, /button, input, select, textarea\s*\{\s*font-family: inherit/);
  assert.match(chart, /useContext\(FontFamilyContext\)/);
  assert.match(chart, /withChartFont\(props.option, main\)/);
});
