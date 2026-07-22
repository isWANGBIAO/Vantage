import test from 'node:test';
import assert from 'node:assert/strict';
import { buildBrowserLocationQuery } from './locationSample.js';

test('buildBrowserLocationQuery forwards complete browser location metadata', () => {
  const query = buildBrowserLocationQuery({
    coords: {
      latitude: 29.8683,
      longitude: 121.544,
      accuracy: 24.5,
    },
    timestamp: 1784600000123,
  });

  assert.equal(
    query,
    'lat=29.8683&lon=121.544&accuracy=24.5&timestamp_ms=1784600000123',
  );
  assert.ok(!query.includes('city'));
  assert.ok(!query.includes('ip'));
});
test('buildBrowserLocationQuery accepts a timestamp convertible to milliseconds', () => {
  const query = buildBrowserLocationQuery({
    coords: { latitude: 0, longitude: 0, accuracy: 1 },
    timestamp: new Date('2026-07-21T00:00:00.000Z'),
  });

  assert.equal(query, 'lat=0&lon=0&accuracy=1&timestamp_ms=1784592000000');
});

test('buildBrowserLocationQuery rejects invalid coordinate metadata', () => {
  const valid = {
    coords: { latitude: 29.8683, longitude: 121.544, accuracy: 24.5 },
    timestamp: 1784600000123,
  };

  for (const position of [
    { ...valid, coords: { ...valid.coords, latitude: Number.NaN } },
    { ...valid, coords: { ...valid.coords, longitude: Number.POSITIVE_INFINITY } },
    { ...valid, coords: { ...valid.coords, latitude: 91 } },
    { ...valid, coords: { ...valid.coords, longitude: -181 } },
    { ...valid, coords: { ...valid.coords, accuracy: 0 } },
    { ...valid, coords: { ...valid.coords, accuracy: -1 } },
    { ...valid, timestamp: 'not-a-timestamp' },
    { ...valid, timestamp: Number.NaN },
    null,
  ]) {
    assert.equal(buildBrowserLocationQuery(position), '');
  }
});
