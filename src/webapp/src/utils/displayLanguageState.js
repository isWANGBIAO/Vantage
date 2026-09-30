import { sanitizeDisplayLanguage } from './displayLanguage.js';
import { readDisplayLanguage, updateDisplayLanguage } from './configurationClient.js';

export async function loadDisplayLanguageState(platform) {
  const state = await readDisplayLanguage(platform);
  return { ...state, displayLanguage: sanitizeDisplayLanguage(state.displayLanguage) };
}

export async function saveDisplayLanguageSetting(displayLanguage, platform) {
  const state = await updateDisplayLanguage(sanitizeDisplayLanguage(displayLanguage), platform);
  return { ...state, displayLanguage: sanitizeDisplayLanguage(state.displayLanguage) };
}
