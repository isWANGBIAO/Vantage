import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const cameraFeedSource = readFileSync(new URL('./CameraFeed.jsx', import.meta.url), 'utf8');

test('CameraFeed button text uses readable ASCII labels', () => {
  assert.ok(cameraFeedSource.includes('DETECTING'));
  assert.ok(cameraFeedSource.includes('OFF'));
  assert.equal(
    [...cameraFeedSource].some((ch) => ch.charCodeAt(0) > 127),
    false,
  );
});
