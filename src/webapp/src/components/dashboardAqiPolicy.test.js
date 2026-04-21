import test from 'node:test';
import assert from 'node:assert/strict';
import { shouldUseDashboardGeolocation } from './dashboardAqiPolicy.js';

test('hidden dashboard skips geolocation when permission would still prompt', () => {
  assert.equal(
    shouldUseDashboardGeolocation({ isVisible: false, permissionState: 'prompt' }),
    false,
  );
  assert.equal(
    shouldUseDashboardGeolocation({ isVisible: false, permissionState: 'denied' }),
    false,
  );
});

test('visible dashboard or granted permission can use geolocation', () => {
  assert.equal(
    shouldUseDashboardGeolocation({ isVisible: true, permissionState: 'prompt' }),
    true,
  );
  assert.equal(
    shouldUseDashboardGeolocation({ isVisible: false, permissionState: 'granted' }),
    true,
  );
});
