function getLaunchAtLoginState({ app } = {}) {
  if (!app || typeof app.getLoginItemSettings !== 'function') {
    return false;
  }

  const settings = app.getLoginItemSettings();
  return Boolean(settings && settings.openAtLogin);
}

function applyLaunchAtLoginSetting({ app, enabled } = {}) {
  const normalizedEnabled = Boolean(enabled);
  if (!app || typeof app.setLoginItemSettings !== 'function') {
    return normalizedEnabled;
  }

  app.setLoginItemSettings({
    openAtLogin: normalizedEnabled,
  });
  return normalizedEnabled;
}

module.exports = {
  applyLaunchAtLoginSetting,
  getLaunchAtLoginState,
};
