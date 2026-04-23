/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  startTransition,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  DEFAULT_DISPLAY_LANGUAGE,
  DISPLAY_LANGUAGE_OPTIONS,
  getBrowserLocale,
  resolveEffectiveDisplayLanguage,
  sanitizeDisplayLanguage,
} from '../utils/displayLanguage.js';
import { translate } from '../utils/displayCopy.js';
import {
  loadDisplayLanguageState,
  saveDisplayLanguageSetting,
} from '../utils/displayLanguageState.js';

const DisplayLanguageContext = createContext(null);

function buildLanguageState({ displayLanguage, systemLocale }) {
  const nextDisplayLanguage = sanitizeDisplayLanguage(displayLanguage);
  const nextSystemLocale = typeof systemLocale === 'string' && systemLocale.trim()
    ? systemLocale
    : getBrowserLocale();

  return {
    displayLanguage: nextDisplayLanguage,
    systemLocale: nextSystemLocale,
    effectiveLanguage: resolveEffectiveDisplayLanguage({
      displayLanguage: nextDisplayLanguage,
      systemLocale: nextSystemLocale,
      browserLocale: getBrowserLocale(),
    }),
  };
}

export function DisplayLanguageProvider({ children }) {
  const [languageState, setLanguageState] = useState(() => buildLanguageState({
    displayLanguage: DEFAULT_DISPLAY_LANGUAGE,
    systemLocale: getBrowserLocale(),
  }));

  useEffect(() => {
    let cancelled = false;

    const initializeLanguageState = async () => {
      const nextState = await loadDisplayLanguageState();
      if (cancelled) {
        return;
      }

      startTransition(() => {
        setLanguageState(buildLanguageState(nextState));
      });
    };

    void initializeLanguageState();

    return () => {
      cancelled = true;
    };
  }, []);

  const setDisplayLanguage = async (nextDisplayLanguage) => {
    const persistedState = await saveDisplayLanguageSetting(nextDisplayLanguage);
    const nextState = buildLanguageState(persistedState);

    startTransition(() => {
      setLanguageState(nextState);
    });

    return nextState;
  };

  const value = useMemo(() => {
    const t = (key, replacements) => translate(languageState.effectiveLanguage, key, replacements);
    const languageOptions = DISPLAY_LANGUAGE_OPTIONS.map((value) => ({
      value,
      label: t(
        value === 'system'
          ? 'app.language.follow_system'
          : value === 'zh-CN'
            ? 'app.language.zh_cn'
            : 'app.language.en_us',
      ),
    }));

    return {
      ...languageState,
      t,
      languageOptions,
      setDisplayLanguage,
    };
  }, [languageState]);

  return (
    <DisplayLanguageContext.Provider value={value}>
      {children}
    </DisplayLanguageContext.Provider>
  );
}

export function useDisplayLanguage() {
  const context = useContext(DisplayLanguageContext);
  if (!context) {
    throw new Error('useDisplayLanguage must be used within DisplayLanguageProvider.');
  }
  return context;
}
