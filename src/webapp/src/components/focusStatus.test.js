import test from 'node:test';
import assert from 'node:assert/strict';

import * as focusStatus from './focusStatus.js';

const { getFocusStatusPresentation } = focusStatus;

const BASE_STATS = {
  status: 'active',
  is_sitting: true,
  duration_minutes: 5,
  duration_seconds: 300,
  threshold_minutes: 20,
};

test('present focus renders the growing trusted duration and threshold', () => {
  assert.deepEqual(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'present',
      duration_minutes: 8,
    }),
    {
      detectionStatus: 'present',
      valueKey: 'dashboard.stat.focus_duration',
      valueParams: { value: 8 },
      detailKey: 'dashboard.stat.focus_present',
      detailParams: { value: 20 },
      isNearLimit: false,
    },
  );
});

test('absent focus keeps the trusted duration visible during grace', () => {
  assert.deepEqual(
    getFocusStatusPresentation({ ...BASE_STATS, detection_status: 'absent' }),
    {
      detectionStatus: 'absent',
      valueKey: 'dashboard.stat.focus_duration',
      valueParams: { value: 5 },
      detailKey: 'dashboard.stat.focus_absent',
      detailParams: undefined,
      isNearLimit: false,
    },
  );
});

test('confirmed absence renders Away and explains that the timer reset', () => {
  assert.deepEqual(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'absent',
      is_sitting: false,
      duration_minutes: 0,
      duration_seconds: 0,
    }),
    {
      detectionStatus: 'absent',
      valueKey: 'dashboard.stat.away',
      valueParams: undefined,
      detailKey: 'dashboard.stat.focus_absent_confirmed',
      detailParams: undefined,
      isNearLimit: false,
    },
  );
});

for (const detectionStatus of ['unknown', 'stale']) {
  test(`${detectionStatus} focus keeps the trusted duration visible while measurement is unavailable`, () => {
    assert.deepEqual(
      getFocusStatusPresentation({
        ...BASE_STATS,
        detection_status: detectionStatus,
        is_sitting: detectionStatus !== 'stale',
      }),
      {
        detectionStatus,
        valueKey: 'dashboard.stat.focus_duration',
        valueParams: { value: 5 },
        detailKey: 'dashboard.stat.focus_unavailable',
        detailParams: undefined,
        isNearLimit: false,
      },
    );
  });
}

test('only a present session near its threshold uses the warning treatment', () => {
  assert.equal(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'present',
      duration_minutes: 16,
    }).isNearLimit,
    true,
  );
  assert.equal(
    getFocusStatusPresentation({
      ...BASE_STATS,
      detection_status: 'stale',
      duration_minutes: 16,
    }).isNearLimit,
    false,
  );
});

test('failed health polling downgrades a trusted snapshot without losing its timer', () => {
  const previous = {
    ...BASE_STATS,
    detection_status: 'present',
  };

  assert.deepEqual(
    focusStatus.degradeFocusHealthSnapshot?.(previous),
    {
      status: 'active',
      detection_status: 'unknown',
      is_sitting: true,
      duration_minutes: 5,
      duration_seconds: 300,
      threshold_minutes: 20,
    },
  );
});

test('failed initial health polling creates a stable unknown zero snapshot', () => {
  assert.deepEqual(
    focusStatus.degradeFocusHealthSnapshot?.(null),
    {
      status: 'active',
      detection_status: 'unknown',
      is_sitting: false,
      duration_minutes: 0,
      duration_seconds: 0,
      threshold_minutes: 0,
    },
  );
});

test('only a complete active health payload is accepted as a fresh snapshot', () => {
  assert.equal(
    focusStatus.isValidFocusHealthSnapshot?.({
      ...BASE_STATS,
      detection_status: 'present',
    }),
    true,
  );
  assert.equal(
    focusStatus.isValidFocusHealthSnapshot?.({
      ...BASE_STATS,
      status: 'error',
      detection_status: 'present',
    }),
    false,
  );
  assert.equal(
    focusStatus.isValidFocusHealthSnapshot?.({
      status: 'active',
      detection_status: 'present',
    }),
    false,
  );
});
