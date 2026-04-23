export const DEFAULT_DISPLAY_LANGUAGE = 'system';
export const SUPPORTED_DISPLAY_LANGUAGES = ['zh-CN', 'en-US'];
export const DISPLAY_LANGUAGE_OPTIONS = ['system', ...SUPPORTED_DISPLAY_LANGUAGES];

export function sanitizeDisplayLanguage(value) {
  return DISPLAY_LANGUAGE_OPTIONS.includes(value) ? value : DEFAULT_DISPLAY_LANGUAGE;
}

export function mapLocaleToSupportedLanguage(locale) {
  const normalizedLocale = typeof locale === 'string' ? locale.trim().toLowerCase() : '';
  if (normalizedLocale.startsWith('zh')) {
    return 'zh-CN';
  }
  return 'en-US';
}

export function resolveEffectiveDisplayLanguage({
  displayLanguage = DEFAULT_DISPLAY_LANGUAGE,
  systemLocale = null,
  browserLocale = null,
} = {}) {
  const nextDisplayLanguage = sanitizeDisplayLanguage(displayLanguage);
  if (nextDisplayLanguage !== DEFAULT_DISPLAY_LANGUAGE) {
    return nextDisplayLanguage;
  }

  return mapLocaleToSupportedLanguage(systemLocale || browserLocale || null);
}

export function getBrowserLocale() {
  return globalThis.navigator?.language || 'en-US';
}
