import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_DISPLAY_LANGUAGE,
  mapLocaleToSupportedLanguage,
  resolveEffectiveDisplayLanguage,
  sanitizeDisplayLanguage,
} from './displayLanguage.js';

test('sanitizeDisplayLanguage only allows system zh-CN and en-US', () => {
  assert.equal(DEFAULT_DISPLAY_LANGUAGE, 'system');
  assert.equal(sanitizeDisplayLanguage('system'), 'system');
  assert.equal(sanitizeDisplayLanguage('zh-CN'), 'zh-CN');
  assert.equal(sanitizeDisplayLanguage('en-US'), 'en-US');
  assert.equal(sanitizeDisplayLanguage('fr-FR'), 'system');
  assert.equal(sanitizeDisplayLanguage(undefined), 'system');
});

test('mapLocaleToSupportedLanguage maps zh locales to Chinese and all others to English', () => {
  assert.equal(mapLocaleToSupportedLanguage('zh-CN'), 'zh-CN');
  assert.equal(mapLocaleToSupportedLanguage('zh-Hans-SG'), 'zh-CN');
  assert.equal(mapLocaleToSupportedLanguage('zh-TW'), 'zh-CN');
  assert.equal(mapLocaleToSupportedLanguage('en-US'), 'en-US');
  assert.equal(mapLocaleToSupportedLanguage('ja-JP'), 'en-US');
  assert.equal(mapLocaleToSupportedLanguage(''), 'en-US');
});

test('resolveEffectiveDisplayLanguage prefers explicit language over system locale', () => {
  assert.equal(
    resolveEffectiveDisplayLanguage({
      displayLanguage: 'zh-CN',
      systemLocale: 'en-US',
      browserLocale: 'en-US',
    }),
    'zh-CN',
  );
  assert.equal(
    resolveEffectiveDisplayLanguage({
      displayLanguage: 'en-US',
      systemLocale: 'zh-CN',
      browserLocale: 'zh-CN',
    }),
    'en-US',
  );
});

test('resolveEffectiveDisplayLanguage follows system locale first and browser locale second', () => {
  assert.equal(
    resolveEffectiveDisplayLanguage({
      displayLanguage: 'system',
      systemLocale: 'zh-CN',
      browserLocale: 'en-US',
    }),
    'zh-CN',
  );
  assert.equal(
    resolveEffectiveDisplayLanguage({
      displayLanguage: 'system',
      systemLocale: null,
      browserLocale: 'zh-Hans',
    }),
    'zh-CN',
  );
  assert.equal(
    resolveEffectiveDisplayLanguage({
      displayLanguage: 'system',
      systemLocale: null,
      browserLocale: null,
    }),
    'en-US',
  );
});
