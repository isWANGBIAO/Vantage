const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_FILES = 6;
const ELECTRON_LOG_PATTERN = /^electron.*\.log.*$/;

function boundUtf8Tail(buffer, maxBytes) {
  if (buffer.length <= maxBytes) {
    return buffer;
  }

  let start = buffer.length - maxBytes;
  while (start < buffer.length && (buffer[start] & 0xc0) === 0x80) {
    start += 1;
  }
  return buffer.subarray(start);
}

function nextRotationPath(logFile) {
  let suffix = 1;
  let candidate = `${logFile}.${suffix}`;

  while (fs.existsSync(candidate)) {
    suffix += 1;
    candidate = `${logFile}.${suffix}`;
  }

  return candidate;
}

function pruneElectronLogs(logFile, maxFiles) {
  const logDirectory = path.dirname(logFile);
  const activePath = path.resolve(logFile);
  const candidates = [];

  for (const name of fs.readdirSync(logDirectory)) {
    if (!ELECTRON_LOG_PATTERN.test(name)) {
      continue;
    }

    const file = path.join(logDirectory, name);
    try {
      const stats = fs.statSync(file);
      if (stats.isFile()) {
        candidates.push({
          file,
          modified: stats.mtimeMs,
          isActive: path.resolve(file) === activePath,
        });
      }
    } catch {
      // A concurrently removed file needs no further retention work.
    }
  }

  candidates.sort((left, right) => {
    if (left.isActive !== right.isActive) {
      return left.isActive ? 1 : -1;
    }
    return left.modified - right.modified || left.file.localeCompare(right.file);
  });

  let excess = candidates.length - maxFiles;
  for (const candidate of candidates) {
    if (excess <= 0) {
      break;
    }
    if (candidate.isActive) {
      continue;
    }

    try {
      fs.unlinkSync(candidate.file);
      excess -= 1;
    } catch {
      // Retention is best-effort and must never re-enter the logger.
    }
  }
}

function appendBoundedEntry(logFile, entryBuffer, maxBytes, maxFiles) {
  let currentSize = 0;
  try {
    currentSize = fs.statSync(logFile).size;
  } catch (error) {
    if (error.code !== 'ENOENT') {
      throw error;
    }
  }

  if (currentSize > 0 && currentSize + entryBuffer.length > maxBytes) {
    fs.renameSync(logFile, nextRotationPath(logFile));
  }

  fs.appendFileSync(logFile, entryBuffer);
  pruneElectronLogs(logFile, maxFiles);
}

function createBoundedLogger({
  logFile,
  consoleObject = console,
  maxBytes = DEFAULT_MAX_BYTES,
  maxFiles = DEFAULT_MAX_FILES,
}) {
  let consoleMirroringEnabled = true;

  function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `[${timestamp}] [${level}] ${message}`;

    if (error) {
      logEntry += `\n  Stack: ${error.stack || error}`;
    }

    logEntry += '\n';
    const entryBuffer = boundUtf8Tail(Buffer.from(logEntry, 'utf8'), maxBytes);
    try {
      appendBoundedEntry(logFile, entryBuffer, maxBytes, maxFiles);
    } catch {
      // Logging failures are isolated here so an exception handler cannot recurse.
    }

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
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_FILES,
};
