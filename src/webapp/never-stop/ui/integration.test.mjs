import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const app = readFileSync(new URL('./App.jsx', import.meta.url), 'utf8');
const live = readFileSync(new URL('./LiveOutput.jsx', import.meta.url), 'utf8');
const runtime = readFileSync(new URL('./RuntimeDisplay.jsx', import.meta.url), 'utf8');

test('shadow UI shares Vantage fonts and retains explicit YaHei standalone fallbacks', () => {
  const css = readFileSync(new URL('./style.css', import.meta.url), 'utf8');
  const families = [...css.matchAll(/font-family:\s*([^;]+);/g)].map((match) => match[1]);
  assert.equal(families.length, 6);
  assert.match(families[0], /^var\(--font-main,/);
  for (const family of families) {
    assert.match(family, /"Microsoft YaHei", "微软雅黑"/);
    assert.ok(family.indexOf('"Microsoft YaHei"') < family.indexOf('monospace')
      || family.indexOf('"Microsoft YaHei"') < family.indexOf('system-ui'));
  }
  for (const family of families.slice(1)) assert.match(family, /^var\(--font-mono,/);
});

test('Never Stop UI uses the unified Vantage bridge and explains one startup setting', () => {
  assert.match(app, /window\.vantagePlatform\?\.neverStop/);
  assert.doesNotMatch(app, /window\.neverStop/);
  assert.doesNotMatch(app, /独立 Demo|独立桌面入口/);
  assert.doesNotMatch(app, /checked=\{!!form\.launchAtLogin\}/);
  assert.match(app, /Vantage 设置/);
});

test('hidden Never Stop page stops state, progress and goal polling', () => {
  assert.match(app, /export default function App\(\{ isVisible = true, openRequest \}\)/);
  assert.match(app, /if \(!isVisible\) return undefined;[\s\S]*?setInterval\(refresh, 2500\)/);
  assert.match(app, /if \(!isVisible\) return undefined;[\s\S]*?setInterval\(readProgress, 1800\)/);
  assert.match(app, /visible=\{isVisible && visible\}/);
  assert.match(app, /if \(!visible\) return undefined;[\s\S]*?setInterval\(read, 1400\)/);
});

test('hidden Never Stop page stops output polling and runtime timer', () => {
  assert.match(live, /export default function LiveOutput\(\{ project, invoke, status, isVisible = true \}\)/);
  assert.match(live, /if \(!isVisible \|\| !expanded\) return/);
  assert.match(runtime, /export default function RuntimeDisplay\(\{ totalRunMs, runTimerStartedAt, isVisible = true \}\)/);
  assert.match(runtime, /if \(!isVisible \|\| clock\.current\.anchor === null\) return/);
  assert.match(app, /<LiveOutput[\s\S]*?isVisible=\{isVisible\}/);
  assert.match(app, /<RuntimeDisplay[\s\S]*?isVisible=\{isVisible\}/);
});

test('execution principles stay editable with guarded save and version conflict handling', () => {
  assert.match(app, /function PrinciplesEditor\(\{ visible, run, onDirty \}\)/);
  assert.match(app, /run\("principles\.save", \{/);
  assert.match(app, /invoke\("principles\.read"\)/);
  assert.match(app, /aria-label="执行原则 Markdown"/);
  assert.match(app, /onDirty\(dirty \|\| !!conflict \|\| saving\)/);
  assert.match(app, /setNotice\("已保存。所有项目从下一轮调用开始使用新原则。"\)/);
  assert.match(app, /<PrinciplesEditor[\s\S]*?visible=\{isVisible && panel === "执行原则"\}/);
  assert.match(app, /if \(!visible\) return undefined;[\s\S]*?setInterval\(read, 1800\)/);
});

test('failed goal save retains its draft without automatic retry loop', () => {
  assert.match(app, /setSaveState\("保存失败，草稿已保留"\)/);
  assert.match(app, /saveState === "保存失败，草稿已保留"/);
  assert.match(app, /pendingRequests\.current > 0/);
});

test('notification project selection is applied even when the view mounts after the click', () => {
  assert.match(app, /export default function App\(\{ isVisible = true, openRequest \}\)/);
  assert.match(app, /openRequest\?\.projectId/);
  assert.match(app, /setSelected\(openRequest\.projectId\)/);
});
