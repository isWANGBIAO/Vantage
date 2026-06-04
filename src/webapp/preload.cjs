const { contextBridge, ipcRenderer } = require('electron');

async function primeRendererCameraAccess() {
    if (!navigator.mediaDevices?.getUserMedia) {
        return {
            granted: false,
            error: 'renderer mediaDevices.getUserMedia is unavailable',
        };
    }

    let stream = null;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        return { granted: true };
    } catch (error) {
        return {
            granted: false,
            error: error?.message || String(error),
        };
    } finally {
        if (stream) {
            for (const track of stream.getTracks()) {
                track.stop();
            }
        }
    }
}

ipcRenderer.on('camera:prime-renderer-access', async () => {
    const result = await primeRendererCameraAccess();
    ipcRenderer.send('camera:renderer-access-result', result);
});

contextBridge.exposeInMainWorld('electronAPI', {
    platform: process.platform,
    showNotification: (title, body) => {
        ipcRenderer.send('show-notification', { title, body });
    },
    minimizeToTray: () => {
        ipcRenderer.send('minimize-to-tray');
    },
    getOnboardingState: () => ipcRenderer.invoke('onboarding:get-state'),
    completeOnboarding: (payload) => ipcRenderer.invoke('onboarding:complete', payload),
    pickLegacyRoot: () => ipcRenderer.invoke('onboarding:pick-legacy-root'),
    getSettingsState: () => ipcRenderer.invoke('settings:get-state'),
    saveSettings: (payload) => ipcRenderer.invoke('settings:save', payload),
    openSettingsPath: (pathKey) => ipcRenderer.invoke('settings:open-path', pathKey),
    getDisplayLanguageState: () => ipcRenderer.invoke('settings:get-display-language-state'),
    setDisplayLanguage: (displayLanguage) => ipcRenderer.invoke('settings:set-display-language', displayLanguage),
    getSystemLocale: () => ipcRenderer.invoke('settings:get-system-locale'),
    setTitleBarTheme: (theme) => ipcRenderer.invoke('window:set-title-bar-theme', theme),
    onMessage: (channel, callback) => {
        const validChannels = ['update-available', 'backend-status'];
        if (validChannels.includes(channel)) {
            ipcRenderer.on(channel, (event, ...args) => callback(...args));
        }
    },
});
