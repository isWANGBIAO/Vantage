import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { EventEmitter } from 'node:events';
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

function createWritableStream(overrides = {}) {
    return Object.assign(new EventEmitter(), {
        destroyed: false,
        writable: true,
    }, overrides);
}

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

test('explicit startup cleanup bounds and globally prunes only Electron logs', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_2026-07-23.log');
    const oversizedLog = path.join(tempDir, 'electron_2026-07-17.log');
    const serverLog = path.join(tempDir, 'server.log');
    const nestedDir = path.join(tempDir, 'nested');
    const nestedElectronLog = path.join(nestedDir, 'electron_deep.log');
    const maxBytes = 96;
    const maxFiles = 3;
    let logger;

    try {
        fs.mkdirSync(nestedDir);
        fs.writeFileSync(
            oversizedLog,
            `legacy-prefix-${'汉'.repeat(100)}-最新有效尾巴\n`,
            'utf8',
        );
        fs.writeFileSync(logFile, 'active-log\n');
        fs.writeFileSync(
            path.join(tempDir, 'electron_2026-07-18.log'),
            'old-log\n',
        );
        fs.writeFileSync(
            path.join(tempDir, 'electron_2026-07-19.log.1'),
            'rotated-log\n',
        );
        fs.writeFileSync(
            path.join(tempDir, 'electron_2026-07-20.log'),
            'newer-log\n',
        );
        fs.writeFileSync(serverLog, Buffer.from([0, 1, 2, 3, 255]));
        fs.writeFileSync(nestedElectronLog, 'z'.repeat(maxBytes * 2));

        const timestamps = [
            ['electron_2026-07-18.log', '2026-07-18T00:00:00.000Z'],
            ['electron_2026-07-19.log.1', '2026-07-19T00:00:00.000Z'],
            ['electron_2026-07-20.log', '2026-07-20T00:00:00.000Z'],
            ['electron_2026-07-23.log', '2026-07-21T00:00:00.000Z'],
            ['electron_2026-07-17.log', '2026-07-22T00:00:00.000Z'],
        ];
        for (const [name, timestamp] of timestamps) {
            const modified = new Date(timestamp);
            fs.utimesSync(path.join(tempDir, name), modified, modified);
        }

        const serverBytesBefore = fs.readFileSync(serverLog);
        const serverMtimeBefore = fs.statSync(serverLog).mtimeMs;
        const nestedBytesBefore = fs.readFileSync(nestedElectronLog);
        const oversizedStatsBefore = fs.statSync(oversizedLog);

        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes,
            maxFiles,
        });

        assert.equal(
            fs.statSync(oversizedLog).size,
            oversizedStatsBefore.size,
            'constructing the logger must not perform startup cleanup',
        );

        assert.doesNotThrow(() => logger.cleanup());

        const electronLogs = listElectronLogs(tempDir);
        assert.ok(electronLogs.length <= maxFiles);
        for (const file of electronLogs) {
            assert.ok(
                fs.statSync(file).size <= maxBytes,
                `${path.basename(file)} exceeded ${maxBytes} bytes`,
            );
        }

        const oversizedTail = fs.readFileSync(oversizedLog, 'utf8');
        assert.doesNotMatch(oversizedTail, /\uFFFD/);
        assert.match(oversizedTail, /最新有效尾巴\n$/);
        assert.equal(
            fs.statSync(oversizedLog).mtimeMs,
            oversizedStatsBefore.mtimeMs,
        );
        assert.deepEqual(fs.readFileSync(serverLog), serverBytesBefore);
        assert.equal(fs.statSync(serverLog).mtimeMs, serverMtimeBefore);
        assert.deepEqual(fs.readFileSync(nestedElectronLog), nestedBytesBefore);
    } finally {
        logger?.dispose();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('startup cleanup reads only a bounded tail of a sparse legacy log', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_2026-07-23.log');
    const maxBytes = 128;
    const sparseSize = 64 * 1024 * 1024;
    const newestTail = Buffer.from(`${'汉'.repeat(30)}-稀疏文件最新尾巴\n`, 'utf8');
    const originalReadSync = fs.readSync;
    const originalReadFileSync = fs.readFileSync;
    let totalBytesRead = 0;
    let largestReadRequest = 0;
    let logger;

    try {
        const descriptor = fs.openSync(logFile, 'w');
        try {
            fs.ftruncateSync(descriptor, sparseSize);
            fs.writeSync(
                descriptor,
                newestTail,
                0,
                newestTail.length,
                sparseSize - newestTail.length,
            );
        } finally {
            fs.closeSync(descriptor);
        }

        try {
            fs.readSync = (...args) => {
                largestReadRequest = Math.max(largestReadRequest, args[3]);
                const bytesRead = originalReadSync(...args);
                totalBytesRead += bytesRead;
                return bytesRead;
            };
            fs.readFileSync = (file, ...args) => {
                if (path.resolve(file) === path.resolve(logFile)) {
                    throw new Error('cleanup must not read the whole legacy log');
                }
                return originalReadFileSync(file, ...args);
            };

            logger = createBoundedLogger({
                logFile,
                consoleObject: silentConsole,
                maxBytes,
                maxFiles: 2,
            });
            logger.cleanup();
        } finally {
            fs.readSync = originalReadSync;
            fs.readFileSync = originalReadFileSync;
        }

        assert.ok(largestReadRequest <= maxBytes + 3);
        assert.ok(totalBytesRead <= maxBytes + 3);
        assert.ok(fs.statSync(logFile).size <= maxBytes);
        const contents = fs.readFileSync(logFile, 'utf8');
        assert.doesNotMatch(contents, /\uFFFD/);
        assert.match(contents, /稀疏文件最新尾巴\n$/);
    } finally {
        fs.readSync = originalReadSync;
        fs.readFileSync = originalReadFileSync;
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('cleanup tolerates disappearing and inaccessible logs without temp leaks', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_current.log');
    const disappearingLog = path.join(tempDir, 'electron_disappearing.log');
    const inaccessibleLog = path.join(tempDir, 'electron_inaccessible.log');
    const originalOpenSync = fs.openSync;
    const originalRenameSync = fs.renameSync;
    let consoleCalls = 0;
    let logger;

    try {
        fs.writeFileSync(disappearingLog, 'd'.repeat(512));
        fs.writeFileSync(inaccessibleLog, 'i'.repeat(512));
        logger = createBoundedLogger({
            logFile,
            consoleObject: {
                log() {
                    consoleCalls += 1;
                },
                error() {
                    consoleCalls += 1;
                },
            },
            maxBytes: 64,
            maxFiles: 10,
        });

        fs.openSync = (file, ...args) => {
            if (path.resolve(file) === path.resolve(disappearingLog)) {
                fs.unlinkSync(disappearingLog);
                const error = new Error('concurrently removed');
                error.code = 'ENOENT';
                throw error;
            }
            return originalOpenSync(file, ...args);
        };
        fs.renameSync = (oldPath, newPath) => {
            if (path.resolve(newPath) === path.resolve(inaccessibleLog)) {
                const error = new Error('access denied');
                error.code = 'EACCES';
                throw error;
            }
            return originalRenameSync(oldPath, newPath);
        };

        assert.doesNotThrow(() => logger.cleanup());
        assert.equal(fs.existsSync(disappearingLog), false);
        assert.ok(fs.statSync(inaccessibleLog).size > 64);
        assert.equal(consoleCalls, 0);
        assert.deepEqual(
            fs.readdirSync(tempDir).filter((name) => name.endsWith('.tmp')),
            [],
        );
    } finally {
        fs.openSync = originalOpenSync;
        fs.renameSync = originalRenameSync;
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('async output stream errors disable mirroring and dispose removes guards', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron.log');
    const stdout = createWritableStream();
    const stderr = createWritableStream();
    let consoleCalls = 0;
    const consoleObject = {
        log() {
            consoleCalls += 1;
        },
        error() {
            consoleCalls += 1;
        },
    };
    const stdoutListenersBefore = stdout.listenerCount('error');
    const stderrListenersBefore = stderr.listenerCount('error');
    const logger = createBoundedLogger({
        logFile,
        consoleObject,
        stdout,
        stderr,
        maxBytes: 1024,
        maxFiles: 2,
    });

    try {
        assert.equal(stdout.listenerCount('error'), stdoutListenersBefore + 1);
        assert.equal(stderr.listenerCount('error'), stderrListenersBefore + 1);

        logger.info('mirrored-before-epipe');
        assert.equal(consoleCalls, 1);

        const error = new Error('broken stderr pipe');
        error.code = 'EPIPE';
        assert.doesNotThrow(() => stderr.emit('error', error));

        logger.info('not-mirrored-after-epipe');
        assert.equal(consoleCalls, 1);
    } finally {
        logger.dispose();
        logger.dispose();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }

    assert.equal(stdout.listenerCount('error'), stdoutListenersBefore);
    assert.equal(stderr.listenerCount('error'), stderrListenersBefore);
});

test('destroyed or non-writable output streams suppress console mirroring', () => {
    const cases = [
        {
            stdout: createWritableStream({ destroyed: true }),
            stderr: createWritableStream(),
        },
        {
            stdout: createWritableStream(),
            stderr: createWritableStream({ writable: false }),
        },
    ];

    for (const [index, streams] of cases.entries()) {
        const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
        const logFile = path.join(tempDir, `electron-${index}.log`);
        let consoleCalls = 0;
        const logger = createBoundedLogger({
            logFile,
            consoleObject: {
                log() {
                    consoleCalls += 1;
                },
            },
            ...streams,
            maxBytes: 1024,
            maxFiles: 2,
        });

        try {
            logger.info('file-only');
            assert.equal(consoleCalls, 0);
            assert.match(fs.readFileSync(logFile, 'utf8'), /file-only/);
        } finally {
            logger.dispose();
            assert.equal(streams.stdout.listenerCount('error'), 0);
            assert.equal(streams.stderr.listenerCount('error'), 0);
            fs.rmSync(tempDir, { recursive: true, force: true });
        }
    }
});

test('file and cleanup failures never throw or re-enter the logger', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'missing', 'electron.log');
    let consoleCalls = 0;
    const consoleObject = {
        log() {
            consoleCalls += 1;
            const error = new Error('broken pipe');
            error.code = 'EPIPE';
            throw error;
        },
    };
    const logger = createBoundedLogger({
        logFile,
        consoleObject,
        maxBytes: 1024,
        maxFiles: 2,
    });

    try {
        assert.doesNotThrow(() => logger.cleanup());
        assert.doesNotThrow(() => logger.info('first'));
        assert.doesNotThrow(() => logger.info('second'));
        assert.equal(consoleCalls, 1);
    } finally {
        logger.dispose();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});
