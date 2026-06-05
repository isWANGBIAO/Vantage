import test from 'node:test';
import assert from 'node:assert/strict';

import { redactSensitiveText } from './sensitiveText.js';

test('redactSensitiveText removes provider api_key values from plain and JSON errors', () => {
  const secret = '2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19';
  const input = `Rate limit exceeded for api_key: ${secret} body={"error":{"message":"api_key: ${secret}"}}`;

  const redacted = redactSensitiveText(input);

  assert.equal(redacted.includes(secret), false);
  assert.ok(redacted.includes('api_key: [REDACTED_API_KEY]'));
});

test('redactSensitiveText removes sk-style keys', () => {
  assert.equal(
    redactSensitiveText('Authorization failed for sk-1234567890abcdef'),
    'Authorization failed for sk-[REDACTED]',
  );
});
