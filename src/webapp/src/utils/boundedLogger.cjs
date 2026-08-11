const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_FILES = 6;
const ELECTRON_LOG_PATTERN = /^electron.*\.log.*$/;
const UTF8_BOUNDARY_BYTES = 3;
const PATH_PREFIX_BOUNDARY_PATTERN = "(?=$|[\\\\/\\s'\":,\\]\\};>)]|[.!?](?=$|\\s))";
const REMOTE_URL_SCHEMES = new Set(['ftp', 'http', 'https', 'ws', 'wss']);

let temporaryFileSequence = 0;

function escapeRegExpCharacter(character) {
  return /[\\^$.*+?()[\]{}|]/.test(character)
    ? `\\${character}`
    : character;
}

function buildPathPrefixPattern(prefix) {
  let pattern = '';
  let previousWasSeparator = false;

  for (const character of prefix) {
    if (character === '/' || character === '\\') {
      if (!previousWasSeparator) {
        pattern += '[\\\\/]+';
      }
      previousWasSeparator = true;
      continue;
    }

    pattern += escapeRegExpCharacter(character);
    previousWasSeparator = false;
  }

  return pattern;
}

function percentHexCharacterPattern(character) {
  if (/[A-Fa-f]/.test(character)) {
    return `[${character.toLowerCase()}${character.toUpperCase()}]`;
  }
  return character;
}

function percentEncodedCharacterPattern(character) {
  return [...Buffer.from(character, 'utf8')]
    .map((byte) => {
      const hex = byte.toString(16).padStart(2, '0');
      return `%${percentHexCharacterPattern(hex[0])}${percentHexCharacterPattern(hex[1])}`;
    })
    .join('');
}

function buildFileUrlCharacterPattern(character, windowsPath) {
  const variants = new Set([
    escapeRegExpCharacter(character),
    percentEncodedCharacterPattern(character),
  ]);
  if (windowsPath && /^[A-Za-z]$/.test(character)) {
    variants.add(percentEncodedCharacterPattern(character.toLowerCase()));
    variants.add(percentEncodedCharacterPattern(character.toUpperCase()));
  }
  return `(?:${[...variants].join('|')})`;
}

function buildFileUrlPrefixPattern(prefix, windowsPath) {
  const normalized = prefix
    .replace(/\\/g, '/')
    .replace(/^\/+/, '');
  let pattern = '';
  let previousWasSeparator = false;

  for (const character of normalized) {
    if (character === '/') {
      if (!previousWasSeparator) {
        pattern += '[\\/]+';
      }
      previousWasSeparator = true;
      continue;
    }

    pattern += buildFileUrlCharacterPattern(character, windowsPath);
    previousWasSeparator = false;
  }

  return pattern;
}

function compilePathPrefixes(pathPrefixes) {
  if (!Array.isArray(pathPrefixes)) {
    return [];
  }

  return pathPrefixes
    .map((mapping, order) => {
      if (
        !mapping
        || typeof mapping.prefix !== 'string'
        || typeof mapping.label !== 'string'
      ) {
        return null;
      }

      const prefix = mapping.prefix.replace(/[\\/]+$/g, '');
      if (!prefix || !mapping.label) {
        return null;
      }

      const windowsPath = /^[A-Za-z]:[\\/]/.test(prefix)
        || /^\\\\/.test(prefix)
        || prefix.includes('\\');
      return {
        label: mapping.label,
        order,
        prefix,
        regex: new RegExp(
          `${buildPathPrefixPattern(prefix)}${PATH_PREFIX_BOUNDARY_PATTERN}`,
          windowsPath ? 'gi' : 'g',
        ),
        fileUrlRegex: new RegExp(
          `${buildFileUrlPrefixPattern(prefix, windowsPath)}${PATH_PREFIX_BOUNDARY_PATTERN}`,
          windowsPath ? 'gi' : 'g',
        ),
      };
    })
    .filter(Boolean)
    .sort((left, right) => (
      right.prefix.length - left.prefix.length || left.order - right.order
    ));
}

function collectUrlContextEvents(value) {
  const events = [];
  const schemePattern = /\b([A-Za-z][A-Za-z0-9+.-]*):\/\//g;
  for (const match of value.matchAll(schemePattern)) {
    events.push({
      index: match.index + match[0].length,
      scheme: match[1].toLowerCase(),
    });
  }

  const resetPattern = /[\s<>"]|[;,](?=\s*['"]?[A-Za-z_][A-Za-z0-9_.-]*\s*=)/g;
  for (const match of value.matchAll(resetPattern)) {
    events.push({ index: match.index, scheme: null });
  }

  events.sort((left, right) => left.index - right.index);
  return events;
}

function collectPathCandidates(value, compiledPathPrefixes) {
  const candidates = [];

  compiledPathPrefixes.forEach((mapping, priority) => {
    for (const match of value.matchAll(mapping.regex)) {
      candidates.push({
        end: match.index + match[0].length,
        encoded: false,
        label: mapping.label,
        priority,
        start: match.index,
      });
    }
    for (const match of value.matchAll(mapping.fileUrlRegex)) {
      candidates.push({
        end: match.index + match[0].length,
        encoded: true,
        label: mapping.label,
        priority,
        start: match.index,
      });
    }
  });

  candidates.sort((left, right) => (
    left.start - right.start
    || left.priority - right.priority
    || right.end - left.end
    || Number(left.encoded) - Number(right.encoded)
  ));
  return candidates;
}

function selectPathReplacements(value, compiledPathPrefixes) {
  const events = collectUrlContextEvents(value);
  const candidates = collectPathCandidates(value, compiledPathPrefixes);
  const replacements = [];
  let activeScheme = null;
  let eventIndex = 0;
  let replacedUntil = 0;

  for (const candidate of candidates) {
    while (
      eventIndex < events.length
      && events[eventIndex].index <= candidate.start
    ) {
      activeScheme = events[eventIndex].scheme;
      eventIndex += 1;
    }

    if (candidate.start < replacedUntil) {
      continue;
    }
    if (activeScheme && REMOTE_URL_SCHEMES.has(activeScheme)) {
      continue;
    }
    if (candidate.encoded && !activeScheme) {
      continue;
    }

    replacements.push(candidate);
    replacedUntil = candidate.end;
  }

  return replacements;
}

function applyPathReplacements(value, replacements) {
  if (replacements.length === 0) {
    return value;
  }

  const segments = [];
  let cursor = 0;
  for (const replacement of replacements) {
    segments.push(value.slice(cursor, replacement.start));
    segments.push(replacement.label);
    cursor = replacement.end;
  }
  segments.push(value.slice(cursor));
  return segments.join('');
}

function redactPathPrefixes(value, compiledPathPrefixes) {
  if (compiledPathPrefixes.length === 0) {
    return value;
  }

  return applyPathReplacements(
    value,
    selectPathReplacements(value, compiledPathPrefixes),
  );
}

function redactSensitiveTextWithCompiledPaths(value, compiledPathPrefixes) {
  return redactPathPrefixes(value, compiledPathPrefixes)
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, 'sk-[REDACTED]')
    .replace(/("api[_-]?key"\s*:\s*")[^"]{8,}(")/gi, '$1[REDACTED_API_KEY]$2')
    .replace(/(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_-]{16,}/gi, '$1[REDACTED_API_KEY]');
}

function redactSensitiveText(value, pathPrefixes = []) {
  if (typeof value !== 'string') {
    return value;
  }

  return redactSensitiveTextWithCompiledPaths(
    value,
    compilePathPrefixes(pathPrefixes),
  );
}

function safeString(value, fallback) {
  if (typeof value === 'string') {
    return value;
  }
  try {
    return String(value);
  } catch {
    return fallback;
  }
}

function safeErrorText(error) {
  try {
    if (error && typeof error === 'object' && error.stack) {
      return safeString(error.stack, '[unprintable error]');
    }
  } catch {
    // Fall through to a guarded conversion of the error itself.
  }
  return safeString(error, '[unprintable error]');
}

function utf8SequenceLength(firstByte) {
  if (firstByte <= 0x7f) {
    return 1;
  }
  if (firstByte >= 0xc2 && firstByte <= 0xdf) {
    return 2;
  }
  if (firstByte >= 0xe0 && firstByte <= 0xef) {
    return 3;
  }
  if (firstByte >= 0xf0 && firstByte <= 0xf4) {
    return 4;
  }
  return 0;
}

function trimIncompleteUtf8End(buffer) {
  if (buffer.length === 0) {
    return buffer;
  }

  let sequenceStart = buffer.length - 1;
  while (
    sequenceStart >= 0
    && (buffer[sequenceStart] & 0xc0) === 0x80
  ) {
    sequenceStart -= 1;
  }

  if (sequenceStart < 0) {
    return buffer.subarray(0, 0);
  }

  const sequenceLength = utf8SequenceLength(buffer[sequenceStart]);
  const availableBytes = buffer.length - sequenceStart;
  if (sequenceLength === 0) {
    return buffer.subarray(0, sequenceStart);
  }
  if (availableBytes < sequenceLength) {
    return buffer.subarray(0, sequenceStart);
  }
  if (availableBytes > sequenceLength) {
    return buffer.subarray(0, sequenceStart + sequenceLength);
  }
  return buffer;
}

function boundUtf8Tail(buffer, maxBytes) {
  let bounded = buffer;
  if (buffer.length > maxBytes) {
    let start = buffer.length - maxBytes;
    while (start < buffer.length && (buffer[start] & 0xc0) === 0x80) {
      start += 1;
    }
    bounded = buffer.subarray(start);
  }

  return trimIncompleteUtf8End(bounded);
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

function collectElectronLogs(logFile) {
  const logDirectory = path.dirname(logFile);
  const activePath = path.resolve(logFile);
  const candidates = [];
  let names;

  try {
    names = fs.readdirSync(logDirectory);
  } catch {
    return candidates;
  }

  for (const name of names) {
    if (!ELECTRON_LOG_PATTERN.test(name)) {
      continue;
    }

    const file = path.join(logDirectory, name);
    try {
      const stats = fs.lstatSync(file);
      if (stats.isFile()) {
        candidates.push({
          file,
          modified: stats.mtimeMs,
          stats,
          isActive: path.resolve(file) === activePath,
        });
      }
    } catch {
      // A concurrently removed file needs no further retention work.
    }
  }

  return candidates;
}

function pruneElectronLogs(logFile, maxFiles, protectedFiles = new Set()) {
  const candidates = collectElectronLogs(logFile);

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
    if (
      candidate.isActive
      || protectedFiles.has(path.resolve(candidate.file))
    ) {
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

function sameFileVersion(left, right) {
  return (
    left.isFile()
    && right.isFile()
    && left.dev === right.dev
    && left.ino === right.ino
    && left.size === right.size
    && left.mtimeMs === right.mtimeMs
    && left.ctimeMs === right.ctimeMs
  );
}

function readBoundedUtf8Tail(descriptor, size, maxBytes) {
  const readLength = Math.min(size, maxBytes + UTF8_BOUNDARY_BYTES);
  const buffer = Buffer.allocUnsafe(readLength);
  const start = size - readLength;
  let totalBytesRead = 0;

  while (totalBytesRead < readLength) {
    const bytesRead = fs.readSync(
      descriptor,
      buffer,
      totalBytesRead,
      readLength - totalBytesRead,
      start + totalBytesRead,
    );
    if (bytesRead === 0) {
      break;
    }
    totalBytesRead += bytesRead;
  }

  return boundUtf8Tail(buffer.subarray(0, totalBytesRead), maxBytes);
}

function readStableBoundedUtf8Tail(candidate, maxBytes) {
  const beforeOpen = fs.lstatSync(candidate.file);
  if (
    !sameFileVersion(candidate.stats, beforeOpen)
    || beforeOpen.size <= maxBytes
  ) {
    return null;
  }

  const descriptor = fs.openSync(candidate.file, 'r');
  try {
    const opened = fs.fstatSync(descriptor);
    if (!sameFileVersion(beforeOpen, opened) || opened.size <= maxBytes) {
      return null;
    }

    const tail = readBoundedUtf8Tail(descriptor, opened.size, maxBytes);
    const afterRead = fs.fstatSync(descriptor);
    if (!sameFileVersion(opened, afterRead)) {
      return null;
    }

    return {
      stats: afterRead,
      tail,
    };
  } finally {
    fs.closeSync(descriptor);
  }
}

function nextTemporaryPath(file) {
  temporaryFileSequence += 1;
  return path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${temporaryFileSequence}.tmp`,
  );
}

function replaceWithBoundedTail(candidate, maxBytes) {
  const stableTail = readStableBoundedUtf8Tail(candidate, maxBytes);
  if (!stableTail) {
    return false;
  }

  const { stats, tail } = stableTail;
  let temporaryPath;

  try {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      temporaryPath = nextTemporaryPath(candidate.file);
      try {
        fs.writeFileSync(temporaryPath, tail, { flag: 'wx' });
        break;
      } catch (error) {
        if (error.code !== 'EEXIST') {
          throw error;
        }
        temporaryPath = null;
      }
    }

    if (!temporaryPath) {
      return;
    }

    try {
      fs.chmodSync(temporaryPath, stats.mode);
    } catch {
      // Preserving permissions is best-effort on Windows and network volumes.
    }
    try {
      fs.utimesSync(
        temporaryPath,
        stats.atime,
        stats.mtime,
      );
    } catch {
      // Retaining the old mtime keeps global pruning deterministic when possible.
    }

    const beforeReplace = fs.lstatSync(candidate.file);
    if (!sameFileVersion(stats, beforeReplace)) {
      return false;
    }

    // A same-directory rename provides an atomic replacement to other readers.
    fs.renameSync(temporaryPath, candidate.file);
    temporaryPath = null;

    try {
      fs.utimesSync(
        candidate.file,
        stats.atime,
        stats.mtime,
      );
    } catch {
      // The replacement is already safe even if timestamp restoration fails.
    }
  } finally {
    if (temporaryPath) {
      try {
        fs.unlinkSync(temporaryPath);
      } catch {
        // Never route cleanup failures back through the logger.
      }
    }
  }

  return true;
}

function cleanupElectronLogs(logFile, maxBytes, maxFiles) {
  const candidates = collectElectronLogs(logFile);
  const protectedFiles = new Set();

  for (const candidate of candidates) {
    if (candidate.stats.size <= maxBytes) {
      continue;
    }
    try {
      if (!replaceWithBoundedTail(candidate, maxBytes)) {
        protectedFiles.add(path.resolve(candidate.file));
      }
    } catch {
      // A disappearing or inaccessible legacy log must not block application startup.
      protectedFiles.add(path.resolve(candidate.file));
    }
  }

  pruneElectronLogs(logFile, maxFiles, protectedFiles);
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
  pathPrefixes = [],
  stdout,
  stderr,
}) {
  let consoleMirroringEnabled = true;
  let disposed = false;
  const compiledPathPrefixes = compilePathPrefixes(pathPrefixes);
  const guardedStreams = new Set();
  const resolvedStreams = [
    stdout === undefined
      ? (consoleObject === console ? process.stdout : null)
      : stdout,
    stderr === undefined
      ? (consoleObject === console ? process.stderr : null)
      : stderr,
  ];

  function disableConsoleMirroring() {
    consoleMirroringEnabled = false;
  }

  for (const stream of resolvedStreams) {
    if (!stream || guardedStreams.has(stream)) {
      continue;
    }
    try {
      stream.on('error', disableConsoleMirroring);
      guardedStreams.add(stream);
    } catch {
      disableConsoleMirroring();
    }
  }

  function outputStreamUnavailable() {
    for (const stream of resolvedStreams) {
      if (stream && (stream.destroyed === true || stream.writable === false)) {
        return true;
      }
    }
    return false;
  }

  function writeLog(level, message, error = null) {
    const timestamp = new Date().toISOString();
    const redactedMessage = redactSensitiveTextWithCompiledPaths(
      safeString(message, '[unprintable message]'),
      compiledPathPrefixes,
    );
    let logEntry = `[${timestamp}] [${level}] ${redactedMessage}`;

    if (error) {
      const redactedError = redactSensitiveTextWithCompiledPaths(
        safeErrorText(error),
        compiledPathPrefixes,
      );
      logEntry += `\n  Stack: ${redactedError}`;
    }

    logEntry += '\n';
    const entryBuffer = boundUtf8Tail(Buffer.from(logEntry, 'utf8'), maxBytes);
    try {
      appendBoundedEntry(logFile, entryBuffer, maxBytes, maxFiles);
    } catch {
      // Logging failures are isolated here so an exception handler cannot recurse.
    }

    if (
      disposed
      || !consoleMirroringEnabled
      || outputStreamUnavailable()
    ) {
      consoleMirroringEnabled = false;
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

  function cleanup() {
    try {
      cleanupElectronLogs(logFile, maxBytes, maxFiles);
    } catch {
      // Startup cleanup is isolated from both the application and this logger.
    }
  }

  function dispose() {
    if (disposed) {
      return;
    }
    disposed = true;
    consoleMirroringEnabled = false;

    for (const stream of guardedStreams) {
      try {
        if (typeof stream.off === 'function') {
          stream.off('error', disableConsoleMirroring);
        } else {
          stream.removeListener('error', disableConsoleMirroring);
        }
      } catch {
        // Stream teardown is best-effort and must never reach the logger.
      }
    }
    guardedStreams.clear();
  }

  return {
    info: (message) => writeLog('INFO', message),
    warn: (message) => writeLog('WARN', message),
    error: (message, error = null) => writeLog('ERROR', message, error),
    cleanup,
    dispose,
  };
}

module.exports = {
  createBoundedLogger,
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_FILES,
  redactSensitiveText,
};
