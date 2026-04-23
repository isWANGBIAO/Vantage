import {
  DEFAULT_DISPLAY_LANGUAGE,
  getBrowserLocale,
  sanitizeDisplayLanguage,
} from './displayLanguage.js';

function resolveElectronAPI(electronAPI) {
  return electronAPI ?? globalThis.window?.electronAPI ?? globalThis.electronAPI;
}

export async function loadDisplayLanguageState(electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  const browserLocale = getBrowserLocale();

  if (!resolvedElectronAPI?.getDisplayLanguageState) {
    return {
      displayLanguage: DEFAULT_DISPLAY_LANGUAGE,
      systemLocale: browserLocale,
      mode: 'browser',
    };
  }

  try {
    const payload = await resolvedElectronAPI.getDisplayLanguageState();
    return {
      displayLanguage: sanitizeDisplayLanguage(payload?.displayLanguage),
      systemLocale: typeof payload?.systemLocale === 'string' ? payload.systemLocale : browserLocale,
      mode: 'electron',
    };
  } catch (error) {
    console.warn('Failed to load display language state from Electron bridge.', error);
    return {
      displayLanguage: DEFAULT_DISPLAY_LANGUAGE,
      systemLocale: browserLocale,
      mode: 'browser',
    };
  }
}

export async function saveDisplayLanguageSetting(displayLanguage, electronAPI) {
  const resolvedElectronAPI = resolveElectronAPI(electronAPI);
  const nextDisplayLanguage = sanitizeDisplayLanguage(displayLanguage);
  const browserLocale = getBrowserLocale();

  if (!resolvedElectronAPI?.setDisplayLanguage) {
    return {
      displayLanguage: nextDisplayLanguage,
      systemLocale: browserLocale,
      mode: 'browser',
    };
  }

  try {
    const payload = await resolvedElectronAPI.setDisplayLanguage(nextDisplayLanguage);
    return {
      displayLanguage: sanitizeDisplayLanguage(payload?.displayLanguage ?? nextDisplayLanguage),
      systemLocale: typeof payload?.systemLocale === 'string' ? payload.systemLocale : browserLocale,
      mode: 'electron',
    };
  } catch (error) {
    console.warn('Failed to persist display language through Electron bridge.', error);
    return {
      displayLanguage: nextDisplayLanguage,
      systemLocale: browserLocale,
      mode: 'browser',
    };
  }
}
