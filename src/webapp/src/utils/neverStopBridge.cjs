function installNeverStopBridge({ ipcMain, getWebContents, isTrustedDocument, getService }) {
  ipcMain.handle('never-stop:invoke', async (event, method, payload = {}) => {
    const contents = getWebContents();
    if (!contents || event.sender !== contents || event.senderFrame !== contents.mainFrame
        || !isTrustedDocument(event.senderFrame?.url)) {
      return { ok: false, error: '无效调用来源' };
    }

    try {
      const service = getService();
      if (!service) throw new Error('Never Stop 尚未就绪，请稍后重试');
      return { ok: true, value: await service.invoke(method, payload) };
    } catch (error) {
      return { ok: false, error: String(error?.message || error).slice(0, 2000) };
    }
  });

  return {
    broadcast(change = {}) {
      const contents = getWebContents();
      if (contents && !contents.isDestroyed?.()) contents.send('never-stop:change', change);
    },
  };
}

module.exports = { installNeverStopBridge };
