const { contextBridge, ipcRenderer } = require('electron');

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
    onMessage: (channel, callback) => {
        const validChannels = ['update-available', 'backend-status'];
        if (validChannels.includes(channel)) {
            ipcRenderer.on(channel, (event, ...args) => callback(...args));
        }
    },
});

window.addEventListener('DOMContentLoaded', () => {
    console.log('Electron preload script loaded');
});
