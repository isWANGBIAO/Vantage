const fs = require('node:fs');

function createBoundedLogger({ logFile, consoleObject = console }) {
  let consoleMirroringEnabled = true;

  function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `[${timestamp}] [${level}] ${message}`;

    if (error) {
      logEntry += `\n  Stack: ${error.stack || error}`;
    }

    logEntry += '\n';
    fs.appendFileSync(logFile, logEntry);

    if (!consoleMirroringEnabled) {
      return;
    }

    try {
      if (level === 'ERROR') {
        consoleObject.error(logEntry);
      } else {
        consoleObject.log(logEntry);
      }
    } catch {
      consoleMirroringEnabled = false;
    }
  }

  return {
    info: (message) => writeLog('INFO', message),
    warn: (message) => writeLog('WARN', message),
    error: (message, error = null) => writeLog('ERROR', message, error),
  };
}

module.exports = {
  createBoundedLogger,
};
