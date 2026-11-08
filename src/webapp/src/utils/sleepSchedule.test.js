import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseSleepDate, isSleepSchedulePayload, formatSleepClock,
  prepareSleepScheduleView, buildSleepScheduleGeometry, nearestSleepRecord,
} from './sleepSchedule.js';

const DAY = 86_400_000;
const iso = (timestamp) => new Date(timestamp).toISOString().slice(0, 10);
function fixture(weekCount = 3) {
  const start = Date.parse('2026-10-12T00:00:00Z');
  const daily = Array.from({ length: weekCount * 7 }, (_, index) => ({
    date: iso(start + index * DAY), bedtime_hour: 25 + Math.floor(index / 7), wake_hour: 33 - Math.floor(index / 7),
  }));
  const weeks = Array.from({ length: weekCount }, (_, index) => ({
    start: iso(start + index * 7 * DAY), end: iso(start + (index * 7 + 6) * DAY),
    record_count: 7, bedtime_hour: 25 + index, wake_hour: 33 - index, partial: false,
  }));
  return { version: 1, latest_date: daily.at(-1).date, daily, weeks, duplicate_day_count: 0 };
}

test('calendar parsing rejects normalized impossible dates and unsafe strings', () => {
  assert.equal(parseSleepDate('2024-02-29'), Date.parse('2024-02-29T00:00:00Z'));
  for (const value of ['2026-02-29', '2026-13-01', '2026-1-01', '2026-01-01T00:00:00Z', '', null, '<img>']) {
    assert.equal(parseSleepDate(value), null);
  }
});

test('metadata opt-in is versioned and legacy payloads retain the old renderer', () => {
  assert.equal(isSleepSchedulePayload(fixture()), true);
  for (const value of [null, {}, { ...fixture(), version: 2 }, { ...fixture(), daily: null }, { ...fixture(), latest_date: 'bad' }]) {
    assert.equal(isSleepSchedulePayload(value), false);
    assert.equal(prepareSleepScheduleView(value), null);
  }
});

test('clock formatting preserves midnight semantics and never coerces missing values', () => {
  assert.equal(formatSleepClock(23.5), '23:30');
  assert.equal(formatSleepClock(24.5), '00:30');
  assert.equal(formatSleepClock(33.25), '09:15');
  assert.equal(formatSleepClock(23 + 59.9 / 60), '00:00');
  for (const value of [null, undefined, '', false, '25', NaN, Infinity, -1]) assert.equal(formatSleepClock(value), null);
});

test('daily and weekly series share a fixed first eligible week baseline', () => {
  const view = prepareSleepScheduleView(fixture());
  assert.equal(view.daily.length, 21);
  assert.equal(view.weeks.length, 3);
  assert.equal(view.baseline.start, '2026-10-12');
  assert.deepEqual(view.weeks.map((week) => week.bedtime_delta), [0, 60, 120]);
  assert.deepEqual(view.weeks.map((week) => week.wake_delta), [0, -60, -120]);
  assert.equal(view.bedtime_change, 60);
  assert.equal(view.wake_change, -60);
  assert.equal(view.daily[7].bedtime_delta, 60);
});

test('calendar ranges change displayed weeks and recompute their explicit baseline', () => {
  const data = fixture(28);
  const month = prepareSleepScheduleView(data, 30);
  const quarter = prepareSleepScheduleView(data, 90);
  const half = prepareSleepScheduleView(data, 180);
  assert.equal(month.weeks.length, 5);
  assert.equal(quarter.weeks.length, 13);
  assert.equal(half.weeks.length, 26);
  for (const view of [month, quarter, half]) {
    assert.equal(view.weeks[0].bedtime_delta, 0);
    assert.equal(view.daily[0].bedtime_delta, 0);
    assert.equal(view.weeks.at(-1).start, data.weeks.at(-1).start);
  }
});

test('insufficient weeks remain gaps and cannot create a false previous-week comparison', () => {
  const data = fixture();
  data.weeks[1] = { ...data.weeks[1], record_count: 3, bedtime_hour: null, wake_hour: null };
  const view = prepareSleepScheduleView(data);
  assert.equal(view.weeks[1].bedtime_delta, null);
  assert.equal(view.bedtime_change, null);
  assert.equal(view.wake_change, null);
  const geometry = buildSleepScheduleGeometry(view);
  assert.equal(geometry.arrows.length, 0);
  assert.ok(geometry.weekPaths.filter((path) => path.start === data.weeks[2].start).every((path) => !path.path.includes('V')));
});

test('omitted entire calendar weeks are synthesized as gaps, not connected or compared', () => {
  const data = fixture();
  data.weeks.splice(1, 1);
  const view = prepareSleepScheduleView(data);
  assert.equal(view.weeks.length, 3);
  assert.equal(view.weeks[1].record_count, 0);
  assert.equal(view.bedtime_change, null);
  assert.equal(buildSleepScheduleGeometry(view).arrows.length, 0);
});

test('missing daily records break paths instead of interpolating across unknown days', () => {
  const data = fixture();
  data.daily = data.daily.filter((_row, index) => index !== 5);
  data.daily[7] = { ...data.daily[7], bedtime_hour: null };
  const view = prepareSleepScheduleView(data);
  const geometry = buildSleepScheduleGeometry(view);
  const bed = geometry.dailyPaths.find((path) => path.key === 'bedtime').path;
  const wake = geometry.dailyPaths.find((path) => path.key === 'wake').path;
  assert.equal((bed.match(/M/g) || []).length, 3);
  assert.equal((wake.match(/M/g) || []).length, 2);
  assert.ok(!bed.includes('NaN'));
});

test('early daily records use an explicit temporary day reference without fabricated weekly curves', () => {
  const data = fixture(1);
  data.weeks[0] = { ...data.weeks[0], record_count: 2 };
  const view = prepareSleepScheduleView(data);
  assert.equal(view.baseline_kind, 'day');
  assert.equal(view.baseline.start, data.daily[0].date);
  assert.ok(view.weeks.every((week) => week.bedtime_delta === null));
  assert.equal(buildSleepScheduleGeometry(view).weekPaths.length, 0);
  assert.equal(buildSleepScheduleGeometry(view).arrows.length, 0);
});

for (const count of [1, 2, 3]) test(`${count} days remain visible before weekly sample requirements are met`, () => {
  const data = fixture(1);
  data.daily = data.daily.slice(0, count);
  data.latest_date = data.daily.at(-1).date;
  data.weeks[0] = { ...data.weeks[0], record_count: count, bedtime_hour: null, wake_hour: null };
  const view = prepareSleepScheduleView(data);
  const geometry = buildSleepScheduleGeometry(view);
  assert.equal(view.baseline_kind, 'day');
  assert.equal(view.daily.length, count);
  assert.ok(geometry.dailyPaths.every((path) => path.path.startsWith('M')));
  assert.equal(geometry.dailyPoints.length, count === 1 ? 2 : 0);
  assert.equal(geometry.weekPaths.length, 0);
  assert.equal(geometry.arrows.length, 0);
  assert.equal(view.bedtime_change, null);
});

test('completely missing valid daily and weekly times retain an honest unavailable state', () => {
  const data = fixture(1);
  data.daily = data.daily.map((row) => ({ ...row, bedtime_hour: null, wake_hour: null }));
  data.weeks[0] = { ...data.weeks[0], record_count: 0, bedtime_hour: null, wake_hour: null };
  const view = prepareSleepScheduleView(data);
  assert.equal(view.baseline_kind, null);
  assert.equal(buildSleepScheduleGeometry(view), null);
});

test('nonconsecutive isolated observations produce visible points without drawing invented connections', () => {
  const data = fixture(1);
  data.daily = [data.daily[0], data.daily[3]];
  data.weeks[0] = { ...data.weeks[0], record_count: 2, bedtime_hour: null, wake_hour: null };
  const geometry = buildSleepScheduleGeometry(prepareSleepScheduleView(data));
  assert.equal(geometry.dailyPoints.length, 4);
  assert.ok(geometry.dailyPaths.every((path) => !path.path.includes('L')));
  assert.ok(geometry.dailyPoints.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y)));
});

test('current partial week ends at the latest observation, not its future Sunday', () => {
  const data = fixture();
  data.latest_date = '2026-10-30';
  data.daily = data.daily.slice(0, 19);
  data.weeks[2] = { ...data.weeks[2], record_count: 5, partial: true };
  const view = prepareSleepScheduleView(data);
  const geometry = buildSleepScheduleGeometry(view, 600);
  assert.equal(view.current_week.end, data.latest_date);
  assert.equal(view.current_week.partial, true);
  assert.equal(view.daily.at(-1).date, data.latest_date);
  for (const path of geometry.weekPaths.filter((item) => item.start === data.weeks[2].start)) {
    assert.equal(path.partial, true);
    assert.equal(Number(path.path.split('H').at(-1)), 588);
  }
});

test('arrows encode earlier downwards and later upwards on weekly connectors only', () => {
  const geometry = buildSleepScheduleGeometry(prepareSleepScheduleView(fixture()), 700, 400);
  assert.equal(geometry.dailyPaths.length, 2);
  assert.equal(geometry.weekPaths.length, 6);
  assert.ok(geometry.arrows.some((arrow) => arrow.key === 'bedtime' && arrow.direction === 'later'));
  assert.ok(geometry.arrows.some((arrow) => arrow.key === 'wake' && arrow.direction === 'earlier'));
  for (const arrow of geometry.arrows) {
    const points = [...arrow.path.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map((match) => [Number(match[1]), Number(match[2])]);
    assert.equal(points.length, 3);
    assert.equal(points[1][1] > points[0][1], arrow.direction === 'earlier');
  }
});

test('axis includes zero and all actual extremes without clipping the daily series', () => {
  const data = fixture();
  data.daily[2] = { ...data.daily[2], wake_hour: 41 };
  const view = prepareSleepScheduleView(data);
  const geometry = buildSleepScheduleGeometry(view, 260, 305);
  assert.ok(geometry.yTicks.some((tick) => tick.value === 0));
  const extreme = view.daily[2].wake_delta;
  assert.ok(geometry.yTicks.at(-1).value > extreme);
  assert.ok(geometry.yTicks[0].value < Math.min(...view.weeks.map((week) => week.wake_delta)));
  assert.ok(geometry.xTicks.length < view.weeks.length || view.weeks.length < 4);
});

test('nearest inspection resolves actual daily and matching weekly values', () => {
  const view = prepareSleepScheduleView(fixture());
  const selected = nearestSleepRecord(view, 0.5);
  assert.equal(selected.record.date, '2026-10-22');
  assert.equal(selected.week.start, '2026-10-19');
  assert.equal(nearestSleepRecord(view, -2).record.date, view.daily[0].date);
  assert.equal(nearestSleepRecord(view, 9).record.date, view.daily.at(-1).date);
  assert.equal(nearestSleepRecord(view, NaN), null);
});

test('terminal date labels align inward in a narrow partial-week chart', () => {
  const data = fixture(13);
  data.daily = data.daily.slice(0, -4).map((row) => ({ ...row, bedtime_hour: 25, wake_hour: 33 }));
  data.latest_date = data.daily.at(-1).date;
  data.weeks = data.weeks.map((week) => ({ ...week, bedtime_hour: 25, wake_hour: 33 }));
  Object.assign(data.weeks.at(-1), {
    end: data.latest_date, record_count: 3, bedtime_hour: null, wake_hour: null, partial: true,
  });
  const geometry = buildSleepScheduleGeometry(prepareSleepScheduleView(data, 180), 240, 305);
  assert.equal(geometry.xTicks[0].anchor, 'start');
  assert.equal(geometry.xTicks.at(-1).anchor, 'end');
  assert.ok(geometry.xTicks.every((tick) => tick.x >= 0 && tick.x <= geometry.width));
});

test('malformed and future records cannot create infinite geometry or replace the latest date', () => {
  const data = fixture();
  data.daily.push({ date: '2026-13-01', bedtime_hour: 20, wake_hour: 30 });
  data.daily.push({ date: '2027-01-01', bedtime_hour: 20, wake_hour: 30 });
  data.daily[1] = { ...data.daily[1], bedtime_hour: Infinity, wake_hour: '33' };
  data.weeks.push({ start: '2027-01-04', end: '2027-01-10', record_count: 7, bedtime_hour: 1, wake_hour: 9 });
  const view = prepareSleepScheduleView(data);
  assert.equal(view.daily.length, 21);
  assert.equal(view.daily[1].bedtime_delta, null);
  assert.equal(view.current_week.start, '2026-10-26');
  assert.ok(!JSON.stringify(buildSleepScheduleGeometry(view)).includes('NaN'));
});

test('input metadata is not mutated by display preparation or geometry', () => {
  const data = fixture();
  const original = JSON.stringify(data);
  buildSleepScheduleGeometry(prepareSleepScheduleView(data));
  assert.equal(JSON.stringify(data), original);
});
