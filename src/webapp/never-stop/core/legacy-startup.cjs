const { readWindowsRegistration } = require('./login-startup.cjs');

async function retireLegacyStartup({ app, platform = process.platform, readRegistration = readWindowsRegistration }) {
  if (platform !== 'win32' || !app.isPackaged) return false;
  const name = 'com.vantage.never-stop';
  if (!(await readRegistration(name)).command) return false;
  app.setLoginItemSettings({ openAtLogin: false, name });
  if ((await readRegistration(name)).command !== null)
    throw Error('Never Stop 旧版自启动项未能清除');
  return true;
}

module.exports = { retireLegacyStartup };
