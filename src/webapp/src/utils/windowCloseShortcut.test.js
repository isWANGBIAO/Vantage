import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
let handleWindowCloseShortcut;
try { ({ handleWindowCloseShortcut } = require('./windowCloseShortcut.cjs')); } catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
}

test('Ctrl+W closes only the current window and consumes the input', () => {
  assert.equal(typeof handleWindowCloseShortcut, 'function');
  let prevented = 0;
  let closed = 0;
  const event = { preventDefault() { prevented++; } };
  const window = { close() { closed++; } };
  assert.equal(handleWindowCloseShortcut(event, { type: 'keyDown', key: 'w', control: true }, window, 'win32'), true);
  assert.equal(prevented, 1);
  assert.equal(closed, 1);
});

test('Command+W on macOS closes the current window', () => {
  assert.equal(typeof handleWindowCloseShortcut, 'function');
  let closed = false;
  assert.equal(handleWindowCloseShortcut({ preventDefault() {} }, { type: 'keyDown', key: 'W', meta: true }, { close() { closed = true; } }, 'darwin'), true);
  assert.equal(closed, true);
});

test('unmodified W, key up, repeats and modified shortcuts are not intercepted', () => {
  assert.equal(typeof handleWindowCloseShortcut, 'function');
  for (const input of [
    { type: 'keyDown', key: 'w' },
    { type: 'keyUp', key: 'w', control: true },
    { type: 'keyDown', key: 'w', control: true, isAutoRepeat: true },
    { type: 'keyDown', key: 'w', control: true, shift: true },
    { type: 'keyDown', key: 'w', control: true, alt: true },
    { type: 'keyDown', key: 'a', control: true },
  ]) {
    assert.equal(handleWindowCloseShortcut({ preventDefault() { assert.fail('must not consume input'); } }, input, { close() { assert.fail('must not close'); } }, 'win32'), false);
  }
});
