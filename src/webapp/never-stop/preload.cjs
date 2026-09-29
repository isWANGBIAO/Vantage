const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('neverStop', {
  async invoke(method, payload = {}) {
    const result = await ipcRenderer.invoke('never-stop:invoke', method, payload);
    if (!result.ok) throw new Error(result.error);
    return result.value;
  },
  onChange(callback) {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('never-stop:change', listener);
    return () => ipcRenderer.removeListener('never-stop:change', listener);
  },
});
