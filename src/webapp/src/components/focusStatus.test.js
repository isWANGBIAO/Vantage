import test from 'node:test';
import assert from 'node:assert/strict';

import * as focusStatus from './focusStatus.js';

const {
  degradeFocusHealthSnapshot,
  getFocusStatusPresentation,
  isValidFocusHealthSnapshot,
} = focusStatus;

function getDurationPresentation(seconds) {
  return focusStatus.getDurationPresentation?.(seconds);
}

const BASE_STATS = {
  status: 'active',
  detection_status: 'present',
  is_sitting: true,
  duration_minutes: 5,
  duration_seconds: 300,
  away_duration_seconds: 0,
  active_timer: 'focus',
  threshold_minutes: 20,
};

const DURATION_BOUNDARIES = [
  [0, 'dashboard.stat.duration_under_minute', undefined],
  [59, 'dashboard.stat.duration_under_minute', undefined],
  [60, 'dashboard.stat.duration_minutes', { value: 1 }],
  [3599, 'dashboard.stat.duration_minutes', { value: 59 }],
  [3600, 'dashboard.stat.duration_hours', { value: 1 }],
  [3660, 'dashboard.stat.duration_hours_minutes', { hours: 1, minutes: 1 }],
  [86399, 'dashboard.stat.duration_hours_minutes', { hours: 23, minutes: 59 }],
  [86400, 'dashboard.stat.duration_days', { value: 1 }],
  [90000, 'dashboard.stat.duration_days_hours', { days: 1, hours: 1 }],
];

for (const [seconds, valueKey, valueParams] of DURATION_BOUNDARIES) {
  test(`duration formatter selects ${valueKey} at ${seconds} seconds`, () => {
    assert.deepEqual(getDurationPresentation(seconds), { valueKey, valueParams });
  });
}

test('duration formatter floors raw seconds and normalizes invalid or negative input', () => {
  assert.deepEqual(getDurationPresentation(119.9), {
    valueKey: 'dashboard.stat.duration_minutes',
    valueParams: { value: 1 },
  });
  for (const value of [-1, Number.NaN, Number.POSITIVE_INFINITY, undefined]) {
    assert.deepEqual(getDurationPresentation(value), {
      valueKey: 'dashboard.stat.duration_under_minute',
      valueParams: undefined,
    });
  }
});

test('present focus uses raw focus seconds, a focus title, and the focus threshold detail', () => {
  assert.deepEqual(
    getFocusStatusPresentation({
      ...BASE_STATS,
      duration_minutes: 999,
      duration_seconds: 3660,
    }),
    {
      detectionStatus: 'present',
      titleKey: 'dashboard.stat.focus_time',
      valueKey: 'dashboard.stat.duration_hours_minutes',
      valueParams: { hours: 1, minutes: 1 },
      detailKey: 'dashboard.stat.focus_present',
      detailParams: { value: 20 },
      isNearLimit: true,
    },
  );
});

test('first trusted absence immediately shows the away timer during focus grace', () => {
  assert.deepEqual(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'absent',
      duration_seconds: 700,
      away_duration_seconds: 59,
      active_timer: 'away',
    }),
    {
      detectionStatus: 'absent',
      titleKey: 'dashboard.stat.away_time',
      valueKey: 'dashboard.stat.duration_under_minute',
      valueParams: undefined,
      detailKey: 'dashboard.stat.focus_absent',
      detailParams: undefined,
      isNearLimit: false,
    },
  );
});

test('confirmed absence keeps growing the away timer while explaining only the focus reset', () => {
  assert.deepEqual(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'absent',
      is_sitting: false,
      duration_minutes: 0,
      duration_seconds: 0,
      away_duration_seconds: 90000,
      active_timer: 'away',
    }),
    {
      detectionStatus: 'absent',
      titleKey: 'dashboard.stat.away_time',
      valueKey: 'dashboard.stat.duration_days_hours',
      valueParams: { days: 1, hours: 1 },
      detailKey: 'dashboard.stat.focus_absent_confirmed',
      detailParams: undefined,
      isNearLimit: false,
    },
  );
});

for (const detectionStatus of ['unknown', 'stale']) {
  test(`${detectionStatus} freezes and displays the focus timer selected by active_timer`, () => {
    assert.deepEqual(
      getFocusStatusPresentation({
        ...BASE_STATS,
        detection_status: detectionStatus,
        is_sitting: false,
        duration_seconds: 3600,
        away_duration_seconds: 90000,
        active_timer: 'focus',
      }),
      {
        detectionStatus,
        titleKey: 'dashboard.stat.focus_time',
        valueKey: 'dashboard.stat.duration_hours',
        valueParams: { value: 1 },
        detailKey: 'dashboard.stat.focus_unavailable',
        detailParams: undefined,
        isNearLimit: false,
      },
    );
  });

  test(`${detectionStatus} freezes and displays the away timer selected by active_timer`, () => {
    assert.deepEqual(
      getFocusStatusPresentation({
        ...BASE_STATS,
        detection_status: detectionStatus,
        duration_seconds: 3600,
        away_duration_seconds: 90000,
        active_timer: 'away',
      }),
      {
        detectionStatus,
        titleKey: 'dashboard.stat.away_time',
        valueKey: 'dashboard.stat.duration_days_hours',
        valueParams: { days: 1, hours: 1 },
        detailKey: 'dashboard.stat.focus_unavailable',
        detailParams: undefined,
        isNearLimit: false,
      },
    );
  });

  test(`${detectionStatus} uses a stable zero focus fallback when active_timer is none`, () => {
    assert.deepEqual(
      getFocusStatusPresentation({
        ...BASE_STATS,
        detection_status: detectionStatus,
        duration_seconds: 3600,
        away_duration_seconds: 90000,
        active_timer: 'none',
      }),
      {
        detectionStatus,
        titleKey: 'dashboard.stat.focus_time',
        valueKey: 'dashboard.stat.duration_under_minute',
        valueParams: undefined,
        detailKey: 'dashboard.stat.focus_unavailable',
        detailParams: undefined,
        isNearLimit: false,
      },
    );
  });
}

test('near-limit warning uses raw focus seconds and is restricted to present', () => {
  assert.equal(
    getFocusStatusPresentation({
      ...BASE_STATS,
      duration_minutes: 999,
      duration_seconds: 959.99,
    }).isNearLimit,
    false,
  );
  assert.equal(
    getFocusStatusPresentation({
      ...BASE_STATS,
      duration_minutes: 0,
      duration_seconds: 960,
    }).isNearLimit,
    true,
  );
  for (const detectionStatus of ['absent', 'unknown', 'stale']) {
    assert.equal(
      getFocusStatusPresentation({
        ...BASE_STATS,
        detection_status: detectionStatus,
        duration_seconds: 999999,
        active_timer: 'focus',
      }).isNearLimit,
      false,
    );
  }
});

test('near-limit warning compares raw focus seconds against a fractional minute threshold', () => {
  const presentation = getFocusStatusPresentation({
    ...BASE_STATS,
    duration_minutes: 0,
    duration_seconds: 24,
    threshold_minutes: 0.5,
  });

  assert.equal(presentation.isNearLimit, true);
  assert.deepEqual(presentation.detailParams, { value: 0.5 });
});

test('failed health polling preserves and normalizes both timers and their selected mode', () => {
  assert.deepEqual(
    degradeFocusHealthSnapshot({
      ...BASE_STATS,
      detection_status: 'absent',
      is_sitting: true,
      duration_minutes: 5.5,
      duration_seconds: 300.75,
      away_duration_seconds: 61.25,
      active_timer: 'away',
      threshold_minutes: 20.5,
    }),
    {
      status: 'active',
      detection_status: 'unknown',
      is_sitting: true,
      duration_minutes: 5.5,
      duration_seconds: 300.75,
      away_duration_seconds: 61.25,
      active_timer: 'away',
      threshold_minutes: 20.5,
    },
  );

  assert.deepEqual(
    degradeFocusHealthSnapshot({
      is_sitting: 'yes',
      duration_minutes: -5,
      duration_seconds: Number.NaN,
      away_duration_seconds: Number.POSITIVE_INFINITY,
      active_timer: 'invalid',
      threshold_minutes: -20,
    }),
    {
      status: 'active',
      detection_status: 'unknown',
      is_sitting: false,
      duration_minutes: 0,
      duration_seconds: 0,
      away_duration_seconds: 0,
      active_timer: 'none',
      threshold_minutes: 0,
    },
  );
});

test('failed initial health polling creates a stable unknown dual-timer snapshot', () => {
  assert.deepEqual(degradeFocusHealthSnapshot(null), {
    status: 'active',
    detection_status: 'unknown',
    is_sitting: false,
    duration_minutes: 0,
    duration_seconds: 0,
    away_duration_seconds: 0,
    active_timer: 'none',
    threshold_minutes: 0,
  });
});

test('only a complete active dual-timer health payload is accepted as a fresh snapshot', () => {
  assert.equal(isValidFocusHealthSnapshot(BASE_STATS), true);

  const invalidVariants = [
    { key: 'status', value: 'error' },
    { key: 'detection_status', value: 'broken' },
    { key: 'is_sitting', value: 1 },
    { key: 'duration_minutes', value: undefined },
    { key: 'duration_minutes', value: -1 },
    { key: 'duration_seconds', value: Number.NaN },
    { key: 'duration_seconds', value: -1 },
    { key: 'away_duration_seconds', value: undefined },
    { key: 'away_duration_seconds', value: Number.NaN },
    { key: 'away_duration_seconds', value: Number.POSITIVE_INFINITY },
    { key: 'away_duration_seconds', value: -1 },
    { key: 'active_timer', value: undefined },
    { key: 'active_timer', value: 'paused' },
    { key: 'threshold_minutes', value: Number.NaN },
    { key: 'threshold_minutes', value: -1 },
  ];

  for (const { key, value } of invalidVariants) {
    assert.equal(
      isValidFocusHealthSnapshot({ ...BASE_STATS, [key]: value }),
      false,
      `${key}=${String(value)} must be rejected`,
    );
  }
});

for (const activeTimer of ['focus', 'away', 'none']) {
  test(`validator accepts active_timer=${activeTimer}`, () => {
    assert.equal(isValidFocusHealthSnapshot({ ...BASE_STATS, active_timer: activeTimer }), true);
  });
}
