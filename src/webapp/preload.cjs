const { contextBridge, ipcRenderer } = require('electron');

// 暴露安全的 API 给渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
    // 平台信息
    platform: process.platform,

    // 示例：发送通知到主进程
    showNotification: (title, body) => {
        ipcRenderer.send('show-notification', { title, body });
    },

    // 示例：最小化到托盘
    minimizeToTray: () => {
        ipcRenderer.send('minimize-to-tray');
    },

    // 监听主进程消息
    onMessage: (channel, callback) => {
        const validChannels = ['update-available', 'backend-status'];
        if (validChannels.includes(channel)) {
            ipcRenderer.on(channel, (event, ...args) => callback(...args));
        }
    }
});

// 页面加载完成后的初始化
window.addEventListener('DOMContentLoaded', () => {
    console.log('Electron preload script loaded');
});
