const DAY_MS = 86_400_000;
const WEEK_MS = 7 * DAY_MS;

export function parseSleepDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) return null;
  return timestamp;
}

const isoDate = (timestamp) => new Date(timestamp).toISOString().slice(0, 10);
const isHour = (value) => Number.isFinite(value) && value >= 0 && value < 72;
const monday = (timestamp) => timestamp - ((new Date(timestamp).getUTCDay() + 6) % 7) * DAY_MS;
const validWeek = (week) => week?.record_count >= 4 && isHour(week.bedtime_hour) && isHour(week.wake_hour);

export function isSleepSchedulePayload(payload) {
  return payload?.version === 1 && Array.isArray(payload.daily) && Array.isArray(payload.weeks)
    && parseSleepDate(payload.latest_date) !== null;
}

export function formatSleepClock(value) {
  if (!isHour(value)) return null;
  const minutes = ((Math.round(value * 60) % 1440) + 1440) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

export function prepareSleepScheduleView(payload, rangeDays = 90) {
  if (!isSleepSchedulePayload(payload)) return null;
  const latest = parseSleepDate(payload.latest_date);
  const completeWeeks = ({ 30: 4, 90: 12, 180: 25 })[rangeDays] ?? 12;
  const dailyMap = new Map();
  for (const row of payload.daily) {
    const timestamp = parseSleepDate(row?.date);
    if (timestamp === null || timestamp > latest) continue;
    dailyMap.set(row.date, {
      date: row.date, timestamp,
      bedtime_hour: isHour(row.bedtime_hour) ? row.bedtime_hour : null,
      wake_hour: isHour(row.wake_hour) ? row.wake_hour : null,
    });
  }
  const weekMap = new Map();
  for (const row of payload.weeks) {
    const start = parseSleepDate(row?.start), end = parseSleepDate(row?.end);
    if (start === null || end === null || start > latest || end < start || end - start >= WEEK_MS
      || monday(start) !== start || !Number.isInteger(row.record_count) || row.record_count < 0 || row.record_count > 7) continue;
    const actualEnd = Math.min(end, latest);
    const sufficient = row.record_count >= 4 && isHour(row.bedtime_hour) && isHour(row.wake_hour);
    weekMap.set(row.start, {
      start: row.start, end: isoDate(actualEnd), start_timestamp: start, end_timestamp: actualEnd,
      record_count: row.record_count,
      bedtime_hour: sufficient ? row.bedtime_hour : null,
      wake_hour: sufficient ? row.wake_hour : null,
      partial: row.partial === true || actualEnd - start < 6 * DAY_MS,
    });
  }
  const availableDates = [...weekMap.values()].map((week) => week.start_timestamp)
    .concat([...dailyMap.values()].map((row) => monday(row.timestamp)));
  const firstAvailable = availableDates.length ? Math.min(...availableDates) : monday(latest);
  const start = Math.max(firstAvailable, monday(latest) - completeWeeks * WEEK_MS);
  const weeks = [];
  for (let timestamp = start; timestamp <= latest; timestamp += WEEK_MS) {
    const key = isoDate(timestamp);
    weeks.push(weekMap.get(key) || {
      start: key, end: isoDate(Math.min(timestamp + 6 * DAY_MS, latest)),
      start_timestamp: timestamp, end_timestamp: Math.min(timestamp + 6 * DAY_MS, latest),
      record_count: 0, bedtime_hour: null, wake_hour: null,
      partial: timestamp + 6 * DAY_MS > latest,
    });
  }
  const eligibleWeek = weeks.find(validWeek) || null;
  const firstDay = [...dailyMap.values()].filter((row) => row.timestamp >= start)
    .sort((a, b) => a.timestamp - b.timestamp)
    .find((row) => isHour(row.bedtime_hour) && isHour(row.wake_hour));
  // Daily observations stay visible before a whole week can be summarized.
  // This temporary reference is not a synthetic weekly statistic.
  const baseline = eligibleWeek || (firstDay ? {
    start: firstDay.date, end: firstDay.date,
    bedtime_hour: firstDay.bedtime_hour, wake_hour: firstDay.wake_hour,
  } : null);
  const delta = (value, key) => baseline && isHour(value) ? (value - baseline[key]) * 60 : null;
  const displayWeeks = weeks.map((week) => ({ ...week,
    bedtime_delta: delta(week.bedtime_hour, 'bedtime_hour'),
    wake_delta: delta(week.wake_hour, 'wake_hour'),
  }));
  const daily = [...dailyMap.values()].filter((row) => row.timestamp >= start)
    .sort((a, b) => a.timestamp - b.timestamp)
    .map((row) => ({ ...row,
      bedtime_delta: delta(row.bedtime_hour, 'bedtime_hour'),
      wake_delta: delta(row.wake_hour, 'wake_hour'),
    }));
  const currentWeek = displayWeeks.at(-1) || null;
  const previousWeek = displayWeeks.at(-2) || null;
  const change = (key) => validWeek(currentWeek) && validWeek(previousWeek)
    && currentWeek.start_timestamp - previousWeek.start_timestamp === WEEK_MS
    ? Math.round((currentWeek[key] - previousWeek[key]) * 60) : null;
  return {
    start, end: latest + DAY_MS, latest_date: payload.latest_date,
    daily, weeks: displayWeeks, baseline, baseline_kind: eligibleWeek ? 'week' : firstDay ? 'day' : null,
    current_week: currentWeek,
    bedtime_change: change('bedtime_hour'), wake_change: change('wake_hour'),
    duplicate_day_count: Number.isInteger(payload.duplicate_day_count) && payload.duplicate_day_count > 0
      ? payload.duplicate_day_count : 0,
  };
}

export function buildSleepScheduleGeometry(view, width = 600, height = 320) {
  if (!view?.baseline) return null;
  const safeWidth = Number.isFinite(width) && width > 0 ? width : 600;
  const left = safeWidth < 400 ? 51 : 64, right = 12, top = 16, bottom = 34;
  const innerWidth = Math.max(1, safeWidth - left - right), innerHeight = height - top - bottom;
  const values = [...view.daily, ...view.weeks].flatMap((row) => [row.bedtime_delta, row.wake_delta]).filter(Number.isFinite);
  const low = Math.min(0, ...values), high = Math.max(0, ...values);
  const step = high - low > 300 ? 60 : 30;
  const min = Math.floor((low - 20) / step) * step, max = Math.ceil((high + 20) / step) * step;
  const x = (timestamp) => left + (timestamp - view.start) / (view.end - view.start) * innerWidth;
  const y = (value) => top + (max - value) / (max - min) * innerHeight;
  const dailyPaths = [], dailyPoints = [], weekPaths = [], arrows = [];
  for (const key of ['bedtime', 'wake']) {
    const field = `${key}_delta`;
    let path = '', previousTimestamp = null;
    for (const row of view.daily) {
      const value = row[field];
      if (!Number.isFinite(value)) { previousTimestamp = null; continue; }
      const command = previousTimestamp !== null && row.timestamp - previousTimestamp <= DAY_MS * 1.5 ? 'L' : 'M';
      path += `${command}${x(row.timestamp + DAY_MS / 2)},${y(value)}`;
      previousTimestamp = row.timestamp;
    }
    dailyPaths.push({ key, path });
    for (let index = 0; index < view.daily.length; index += 1) {
      const row = view.daily[index];
      if (!Number.isFinite(row[field])) continue;
      const before = view.daily[index - 1], after = view.daily[index + 1];
      const connectedBefore = before && Number.isFinite(before[field]) && row.timestamp - before.timestamp <= DAY_MS * 1.5;
      const connectedAfter = after && Number.isFinite(after[field]) && after.timestamp - row.timestamp <= DAY_MS * 1.5;
      if (!connectedBefore && !connectedAfter) dailyPoints.push({ key, date: row.date,
        x: x(row.timestamp + DAY_MS / 2), y: y(row[field]) });
    }
    let previous = null;
    for (const week of view.weeks) {
      const value = week[field];
      if (!Number.isFinite(value)) { previous = null; continue; }
      const xx = x(week.start_timestamp), yy = y(value);
      const connected = previous && week.start_timestamp - previous.start_timestamp === WEEK_MS
        && previous.end_timestamp + DAY_MS === week.start_timestamp;
      const prior = connected ? previous[field] : null;
      const segment = `${connected ? `M${xx},${y(prior)}V${yy}` : `M${xx},${yy}`}H${x(Math.min(view.end, week.end_timestamp + DAY_MS))}`;
      weekPaths.push({ key, path: segment, partial: week.partial, start: week.start });
      if (connected && Math.abs(y(prior) - yy) >= 9) {
        const direction = value < prior ? 'earlier' : 'later';
        const sign = direction === 'earlier' ? 1 : -1;
        const mid = (y(prior) + yy) / 2;
        arrows.push({ key, direction, start: week.start,
          path: `M${xx - 4},${mid - sign * 3}L${xx},${mid + sign * 3}L${xx + 4},${mid - sign * 3}` });
      }
      previous = week;
    }
  }
  const yTicks = [];
  for (let value = min; value <= max; value += step) yTicks.push({ value, y: y(value) });
  const tickStep = safeWidth < 420 ? 4 : 2;
  const xTicks = view.weeks.filter((_week, index) => index % tickStep === 0)
    .map((week) => {
      const position = x(week.start_timestamp);
      return { date: week.start, x: position, anchor: position > safeWidth - 50 ? 'end' : 'start' };
    });
  return { width: safeWidth, height, left, right, top, bottom, innerWidth,
    dailyPaths, dailyPoints, weekPaths, arrows, yTicks, xTicks, x, y };
}

export function nearestSleepRecord(view, ratio) {
  if (!view?.daily.length || !Number.isFinite(ratio)) return null;
  const target = view.start + Math.min(1, Math.max(0, ratio)) * (view.end - view.start) - DAY_MS / 2;
  const record = view.daily.reduce((best, row) => Math.abs(row.timestamp - target) < Math.abs(best.timestamp - target) ? row : best);
  const week = view.weeks.find((item) => record.timestamp >= item.start_timestamp && record.timestamp <= item.end_timestamp) || null;
  return { record, week };
}
