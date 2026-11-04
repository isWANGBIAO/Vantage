import test from 'node:test';
import assert from 'node:assert/strict';
import { getStorageForecastPresentation } from './storageForecast.js';
import { translate } from '../utils/displayCopy.js';

const ready = {
  status: 'ready', days_remaining: 123.45,
  average_capture_bytes: 1.5 * 1024 * 1024,
  sample_count: 8, observation_seconds: 420, bytes_per_second: 26214.4,
};
const label = (part, language = 'zh-CN') => translate(language, part.key, part.params);

test('storage forecast presents the measured backend estimate without recalculating from archive size', () => {
  const presentation = getStorageForecastPresentation(ready);
  assert.equal(label(presentation.remaining), '约剩 123.5 天');
  assert.equal(label(presentation.averageCapture), '平均每次采集 1.50 MB');
  assert.equal(label(presentation.remaining, 'en-US'), '~123.5 Days left');
});

test('missing, collecting, and legacy payloads do not present unknown duration as zero', () => {
  for (const forecast of [undefined, null, {}, { days_remaining: 42 }, { ...ready, status: 'insufficient_data' }]) {
    const presentation = getStorageForecastPresentation(forecast);
    assert.equal(label(presentation.remaining), '暂无法估算');
    assert.equal(label(presentation.averageCapture), '暂无法估算');
    assert.equal(label(presentation.remaining, 'en-US'), 'Unable to estimate yet');
  }
});

test('malformed duration values are unavailable rather than coerced or rounded to zero', () => {
  for (const days_remaining of [undefined, null, '', '0', false, -1, NaN, Infinity, -Infinity]) {
    const presentation = getStorageForecastPresentation({ ...ready, days_remaining });
    assert.equal(label(presentation.remaining), '暂无法估算');
  }
});

test('small positive estimates remain distinct from a genuinely full disk', () => {
  const small = getStorageForecastPresentation({ ...ready, days_remaining: 0.001 });
  assert.equal(label(small.remaining), '约剩不足 0.1 天');
  assert.equal(label(small.remaining, 'en-US'), 'Less than 0.1 days left');
  assert.equal(label(getStorageForecastPresentation({ ...ready, days_remaining: 0 }).remaining), '约剩 0.0 天');
  assert.equal(label(getStorageForecastPresentation({ ...ready, days_remaining: 0.1 }).remaining), '约剩 0.1 天');
});

test('invalid average capture bytes do not fabricate zero-sized captures', () => {
  for (const average_capture_bytes of [undefined, null, 0, -1, NaN, Infinity, '1048576']) {
    const presentation = getStorageForecastPresentation({ ...ready, average_capture_bytes });
    assert.equal(label(presentation.averageCapture), '暂无法估算');
  }
});
