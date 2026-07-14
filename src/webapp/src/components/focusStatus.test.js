import test from 'node:test';
import assert from 'node:assert/strict';

import { getFocusStatusPresentation } from './focusStatus.js';

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
