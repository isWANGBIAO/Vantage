import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import boundedLogger from './boundedLogger.cjs';

const {
    createBoundedLogger,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
} = boundedLogger;

const ELECTRON_LOG_PATTERN = /^electron.*\.log.*$/;

function listElectronLogs(directory) {
    return fs.readdirSync(directory)
        .filter((name) => ELECTRON_LOG_PATTERN.test(name))
        .map((name) => path.join(directory, name));
}

const silentConsole = {
    log() {},
    error() {},
};

test('uses the production size and global retention defaults', () => {
    assert.equal(DEFAULT_MAX_BYTES, 10 * 1024 * 1024);
    assert.equal(DEFAULT_MAX_FILES, 6);
});

test('keeps writing after console output fails with EPIPE', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron.log');
    let consoleCalls = 0;
    const consoleObject = {
        log() {
            consoleCalls += 1;
            const error = new Error('broken pipe');
            error.code = 'EPIPE';
            throw error;
        },
    };

    try {
        const logger = createBoundedLogger({
            logFile,
            consoleObject,
            maxBytes: 1024,
            maxFiles: 3,
        });

        assert.doesNotThrow(() => logger.info('first'));
        assert.doesNotThrow(() => logger.info('second'));
        assert.equal(consoleCalls, 1);

        const contents = fs.readFileSync(logFile, 'utf8');
        assert.match(contents, /\[[^\]]+\] \[INFO\] first\n/);
        assert.match(contents, /\[[^\]]+\] \[INFO\] second\n/);
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('bounds every Electron log and prunes retention globally across dates', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_2026-07-23.log');
    const maxBytes = 180;
    const maxFiles = 3;

    try {
        for (let day = 18; day <= 21; day += 1) {
            const oldLog = path.join(tempDir, `electron_2026-07-${day}.log`);
            fs.writeFileSync(oldLog, `legacy-${day}\n`);
            const modified = new Date(`2026-07-${day}T00:00:00.000Z`);
            fs.utimesSync(oldLog, modified, modified);
        }

        const logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes,
            maxFiles,
        });

        for (let index = 0; index < 8; index += 1) {
            logger.info(`entry-${index}-${'x'.repeat(100)}`);
        }
        logger.info('newest-entry');

        const electronLogs = listElectronLogs(tempDir);
        assert.ok(electronLogs.length <= maxFiles);
        for (const file of electronLogs) {
            assert.ok(
                fs.statSync(file).size <= maxBytes,
                `${path.basename(file)} exceeded ${maxBytes} bytes`,
            );
        }

        const retainedContents = electronLogs
            .map((file) => fs.readFileSync(file, 'utf8'))
            .join('');
        assert.match(retainedContents, /newest-entry/);
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('bounds one oversized UTF-8 entry while retaining its newest content', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_2026-07-23.log');
    const maxBytes = 64;

    try {
        const logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes,
            maxFiles: 2,
        });

        logger.info(`oldest-${'汉'.repeat(100)}-最新尾声`);

        const electronLogs = listElectronLogs(tempDir);
        assert.equal(electronLogs.length, 1);
        assert.ok(fs.statSync(electronLogs[0]).size <= maxBytes);

        const contents = fs.readFileSync(electronLogs[0], 'utf8');
        assert.doesNotMatch(contents, /\uFFFD/);
        assert.match(contents, /最新尾声\n$/);
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});
