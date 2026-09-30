import { getBrowserLocale } from './displayLanguage.js';

/** The UI depends on these capabilities, never on Electron globals or Node APIs. */
export function createPlatformAdapter(bridge = null) {
  const descriptor = bridge?.descriptor || {};
  const available = (name, operation) => descriptor.capabilities?.[name] !== false && typeof operation === 'function';
  const capabilities = Object.freeze({
    customTitleBar: descriptor.capabilities?.customTitleBar === true,
    openSettingsPath: available('openSettingsPath', bridge?.openSettingsPath),
    pickLegacyRoot: available('pickLegacyRoot', bridge?.pickLegacyRoot),
    launchAtLogin: descriptor.capabilities?.launchAtLogin === true,
    cameraAccess: available('cameraAccess', bridge?.requestCameraAccess),
    notifications: available('notifications', bridge?.showNotification),
    minimizeToTray: available('minimizeToTray', bridge?.minimizeToTray),
    systemLocale: true,
  });
  return Object.freeze({
    kind: descriptor.kind || 'browser',
    os: descriptor.os || null,
    capabilities,
    app: Object.freeze({ ...(descriptor.app || {}) }),
    backend: Object.freeze({
      connection: descriptor.backend || null,
      waitUntilReady: () => bridge?.waitUntilBackendReady?.() ?? Promise.resolve(),
      requestJson: typeof bridge?.requestConfiguration === 'function'
        ? (method, path, payload) => bridge.requestConfiguration(method, path, payload)
        : null,
    }),
    window: Object.freeze({
      setTitleBarTheme: async (theme) => await bridge?.setTitleBarTheme?.(theme) ?? { applied: false },
      minimizeToTray: () => capabilities.minimizeToTray ? bridge.minimizeToTray() : false,
    }),
    paths: Object.freeze({
      openSettingsPath: (key) => capabilities.openSettingsPath
        ? bridge.openSettingsPath(key) : Promise.resolve({ opened: false }),
      pickLegacyRoot: () => capabilities.pickLegacyRoot
        ? bridge.pickLegacyRoot() : Promise.resolve({ path: null }),
    }),
    locale: Object.freeze({
      getSystemLocale: async () => await bridge?.getSystemLocale?.() || descriptor.systemLocale || getBrowserLocale(),
    }),
    preferences: Object.freeze({
      applySaved: () => bridge?.applySavedPreferences?.() ?? Promise.resolve({ applied: false }),
    }),
    camera: Object.freeze({
      requestAccess: () => capabilities.cameraAccess
        ? bridge.requestCameraAccess() : Promise.resolve({ granted: false, supported: false }),
    }),
    notifications: Object.freeze({
      show: (title, body) => capabilities.notifications ? bridge.showNotification(title, body) : false,
    }),
  });
}

let cachedBridge;
let cachedAdapter;

export function getPlatformAdapter() {
  const bridge = globalThis.window?.vantagePlatform ?? globalThis.vantagePlatform ?? null;
  if (!cachedAdapter || cachedBridge !== bridge) {
    cachedBridge = bridge;
    cachedAdapter = createPlatformAdapter(bridge);
  }
  return cachedAdapter;
}
