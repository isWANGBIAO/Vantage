import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import test from 'node:test';

import boundedLogger from './boundedLogger.cjs';

const {
    createBoundedLogger,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    redactSensitiveText,
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

test('redacts explicit path prefixes without rewriting URLs or diagnostics', () => {
    const secret = '2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19';
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice', label: '<user-home>' },
        {
            prefix: 'C:\\Users\\Alice\\AppData\\Roaming\\Vantage',
            label: '<runtime-data>',
        },
        { prefix: 'D:\\work\\Vantage[dev]', label: '<project-root>' },
    ];
    const url = 'https://example.test/D:/work/Vantage[dev]/guide';
    const value = [
        'home=C:\\USERS\\ALICE\\Desktop\\note.txt',
        'runtime=c:/users/alice/appdata/roaming/vantage/logs/electron.log',
        'project=D:/work/Vantage[dev]/src/main.cjs:123:45',
        `url=${url}`,
        `api_key: ${secret}`,
    ].join('\n');

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.match(redacted, /home=<user-home>\\Desktop\\note\.txt/);
    assert.match(redacted, /runtime=<runtime-data>\/logs\/electron\.log/);
    assert.match(redacted, /project=<project-root>\/src\/main\.cjs:123:45/);
    assert.match(redacted, new RegExp(`url=${url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));
    assert.doesNotMatch(redacted, /<user-home>\/AppData/i);
    assert.doesNotMatch(redacted, new RegExp(secret));
    assert.match(redacted, /api_key: \[REDACTED_API_KEY\]/);
    assert.equal(redactSensitiveText(42, pathPrefixes), 42);
});

test('redacts local file URLs and exact diagnostic roots without touching siblings', () => {
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice\\repo', label: '<project-root>' },
    ];
    const remoteUrl = 'https://example.test/C:/Users/Alice/repo/guide';
    const value = [
        'stack=at start (file:///C:/Users/Alice/repo/src/main.cjs:42:7)',
        'bundle=webpack:///C:/Users/Alice/repo/src/chunk.cjs:5:6',
        'cwd="C:\\Users\\Alice\\repo"',
        'diagnostic=C:/Users/Alice/repo:',
        'sibling=C:/Users/Alice/repo-other/main.cjs',
        'archive=C:/Users/Alice/repo.txt',
        'longer=C:/Users/Alice/repository/main.cjs',
        'plus=C:/Users/Alice/repo+other/main.cjs',
        'paren=C:/Users/Alice/repo(backup)/main.cjs',
        'at=C:/Users/Alice/repo@old/main.cjs',
        'tilde=C:/Users/Alice/repo~old/main.cjs',
        'hash=C:/Users/Alice/repo#old/main.cjs',
        `remote=${remoteUrl}`,
    ].join('\n');

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.match(
        redacted,
        /stack=at start \(file:\/\/\/<project-root>\/src\/main\.cjs:42:7\)/,
    );
    assert.match(
        redacted,
        /bundle=webpack:\/\/\/<project-root>\/src\/chunk\.cjs:5:6/,
    );
    assert.match(redacted, /cwd="<project-root>"/);
    assert.match(redacted, /diagnostic=<project-root>:/);
    assert.match(redacted, /sibling=C:\/Users\/Alice\/repo-other\/main\.cjs/);
    assert.match(redacted, /archive=C:\/Users\/Alice\/repo\.txt/);
    assert.match(redacted, /longer=C:\/Users\/Alice\/repository\/main\.cjs/);
    assert.match(redacted, /plus=C:\/Users\/Alice\/repo\+other\/main\.cjs/);
    assert.match(redacted, /paren=C:\/Users\/Alice\/repo\(backup\)\/main\.cjs/);
    assert.match(redacted, /at=C:\/Users\/Alice\/repo@old\/main\.cjs/);
    assert.match(redacted, /tilde=C:\/Users\/Alice\/repo~old\/main\.cjs/);
    assert.match(redacted, /hash=C:\/Users\/Alice\/repo#old\/main\.cjs/);
    assert.match(
        redacted,
        new RegExp(`remote=${remoteUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
    );
});

test('redacts percent-encoded local file URLs without decoding remote or malformed URLs', () => {
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice Smith\\repo', label: '<spaced-root>' },
        { prefix: 'C:\\Users\\王表\\repo', label: '<unicode-root>' },
        { prefix: '/Users/王表/repo', label: '<posix-unicode-root>' },
        { prefix: '/Users/Alice?Dev/repo', label: '<posix-question-root>' },
        { prefix: 'C:\\Users\\Alice~Dev\\repo', label: '<tilde-root>' },
        { prefix: "C:\\Users\\O'Neil\\repo", label: '<apostrophe-root>' },
    ];
    const remoteUrl = 'https://example.test/C:/Users/Alice%20Smith/repo/guide';
    const malformedFileUrl = 'file:///C:/Users/Alice%2/repo/main.cjs';
    const value = [
        'at file:///C:/Users/Alice%20Smith/repo/src/main.cjs:42:7',
        'at file:///C:/Users/%E7%8E%8B%E8%A1%A8/repo/src/main.cjs:8:2',
        'at file:///Users/%e7%8e%8b%e8%a1%a8/repo/src/main.cjs:9:3',
        'at file:///Users/Alice%3fDev/repo/src/main.cjs:10:4',
        'at file:///C:/Users/Alice%7eDev/repo/src/main.cjs:11:5',
        "at file:///C:/Users/O'Neil/repo/src/main.cjs:12:6",
        `remote=${remoteUrl}`,
        `malformed=${malformedFileUrl}`,
    ].join('\n');

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.match(redacted, /file:\/\/\/<spaced-root>\/src\/main\.cjs:42:7/);
    assert.match(redacted, /file:\/\/\/<unicode-root>\/src\/main\.cjs:8:2/);
    assert.match(
        redacted,
        /file:\/\/\/<posix-unicode-root>\/src\/main\.cjs:9:3/,
    );
    assert.match(
        redacted,
        /file:\/\/\/<posix-question-root>\/src\/main\.cjs:10:4/,
    );
    assert.match(redacted, /file:\/\/\/<tilde-root>\/src\/main\.cjs:11:5/);
    assert.match(
        redacted,
        /file:\/\/\/<apostrophe-root>\/src\/main\.cjs:12:6/,
    );
    assert.match(
        redacted,
        new RegExp(`remote=${remoteUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
    );
    assert.match(
        redacted,
        new RegExp(`malformed=${malformedFileUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
    );
});

test('redacts every local file URL when remote and local URLs share one token', () => {
    const pathPrefixes = [
        { prefix: "C:\\Users\\O'Neil\\repo", label: '<apostrophe-root>' },
    ];
    const value = [
        "urls='https://example.test','file:///C:/Users/O'Neil/repo/src/one.cjs:1:2'",
        "https://example.test/guide;local='file:///C:/Users/O'Neil/repo/src/two.cjs:3:4'",
    ].join('\n');

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.match(redacted, /https:\/\/example\.test/);
    assert.match(redacted, /file:\/\/\/<apostrophe-root>\/src\/one\.cjs:1:2/);
    assert.match(redacted, /file:\/\/\/<apostrophe-root>\/src\/two\.cjs:3:4/);
    assert.doesNotMatch(redacted, /C:\/Users\/O'Neil\/repo/);
});

test('ends remote URL context at structured diagnostic field boundaries', () => {
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice\\repo', label: '<project-root>' },
    ];
    const trueRemoteUrl = 'https://example.test/path;matrix,part/C:/Users/Alice/repo/guide';
    const value = [
        'remote=https://example.test;cwd=C:/Users/Alice/repo/src/main.cjs',
        'remote=https://example.test,cwd=C:/Users/Alice/repo/src/worker.cjs',
        "remote='https://example.test';cwd='C:/Users/Alice/repo/src/quoted.cjs'",
        `actual=${trueRemoteUrl}`,
    ].join('\n');

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.match(redacted, /cwd=<project-root>\/src\/main\.cjs/);
    assert.match(redacted, /cwd=<project-root>\/src\/worker\.cjs/);
    assert.match(redacted, /cwd='<project-root>\/src\/quoted\.cjs'/);
    assert.match(
        redacted,
        new RegExp(`actual=${trueRemoteUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`),
    );
});

test('collects every path replacement from one immutable source value', () => {
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice\\repo', label: '<alice-root>' },
        { prefix: 'C:\\Users\\Bob Smith\\repo', label: '<bob-root>' },
    ];
    const value = (
        'file:///C:/Users/Alice/repo/index.html'
        + '?next=C:/Users/Bob%20Smith/repo/secret.txt'
    );

    const redacted = redactSensitiveText(value, pathPrefixes);

    assert.equal(
        redacted,
        'file:///<alice-root>/index.html?next=<bob-root>/secret.txt',
    );
});

test('requires a real left boundary before Windows and POSIX path prefixes', () => {
    const windowsValue = [
        'embedded=XC:/Users/Alice/repo/src/main.cjs',
        'valid=C:/Users/Alice/repo/src/worker.cjs',
    ].join('\n');
    const posixValue = [
        'partial=file:///NotUsers/Alice/repo/src/main.cjs',
        'valid=file:///Users/Alice/repo/src/main.cjs',
        'compact=path:/Users/Alice/repo/src/compact.cjs',
    ].join('\n');

    const windowsRedacted = redactSensitiveText(windowsValue, [
        { prefix: 'C:\\Users\\Alice\\repo', label: '<windows-root>' },
    ]);
    const posixRedacted = redactSensitiveText(posixValue, [
        { prefix: '/Users/Alice/repo', label: '<posix-root>' },
    ]);

    assert.match(windowsRedacted, /embedded=XC:\/Users\/Alice\/repo\/src\/main\.cjs/);
    assert.match(windowsRedacted, /valid=<windows-root>\/src\/worker\.cjs/);
    assert.match(posixRedacted, /partial=file:\/\/\/NotUsers\/Alice\/repo\/src\/main\.cjs/);
    assert.match(posixRedacted, /valid=file:\/\/\/<posix-root>\/src\/main\.cjs/);
    assert.match(posixRedacted, /compact=path:<posix-root>\/src\/compact\.cjs/);
});

test('redacts many path matches without quadratic rescanning', () => {
    const pathPrefixes = [
        { prefix: 'C:\\Users\\Alice\\repo', label: '<project-root>' },
    ];
    const value = Array.from(
        { length: 10_000 },
        (_, index) => `C:/Users/Alice/repo/${index}`,
    ).join(' ');

    const startedAt = performance.now();
    const redacted = redactSensitiveText(value, pathPrefixes);
    const elapsedMs = performance.now() - startedAt;

    assert.doesNotMatch(redacted, /C:\/Users\/Alice\/repo/);
    assert.equal(redacted.match(/<project-root>/g)?.length, 10_000);
    assert.ok(elapsedMs < 1_000, `redaction took ${elapsedMs.toFixed(1)}ms`);
});

test('redacts messages and error stacks before file and console output', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron.log');
    const mirroredEntries = [];
    const consoleObject = {
        log(entry) {
            mirroredEntries.push(entry);
        },
        error(entry) {
            mirroredEntries.push(entry);
        },
    };
    const secret = '2615cad9be45f50badccd2fa5ffc2bd4596c01eb937c5204388a9c59dfc77b19';
    const error = new Error('backend failed');
    error.stack = [
        'Error: backend failed',
        '    at start (D:\\Projects\\Vantage+prod\\src\\main.cjs:42:7)',
        '    at executable (C:/Program Files/Vantage+/Vantage.exe:1:2)',
    ].join('\n');

    try {
        const logger = createBoundedLogger({
            logFile,
            consoleObject,
            stdout: null,
            stderr: null,
            pathPrefixes: [
                { prefix: 'C:\\Users\\Alice', label: '<user-home>' },
                {
                    prefix: 'C:\\Users\\Alice\\AppData\\Roaming\\Vantage',
                    label: '<runtime-data>',
                },
                { prefix: 'D:\\Projects\\Vantage+prod', label: '<project-root>' },
                { prefix: 'C:\\Program Files\\Vantage+', label: '<app-executable>' },
            ],
            maxBytes: 4096,
            maxFiles: 2,
        });

        logger.error(
            `Cannot open c:/users/alice/appdata/roaming/vantage/cache/state.json api_key=${secret}`,
            error,
        );
        assert.doesNotThrow(() => logger.error('Opaque failure', Symbol('opaque')));

        const contents = fs.readFileSync(logFile, 'utf8');
        const mirrored = mirroredEntries.join('\n');
        for (const output of [contents, mirrored]) {
            assert.match(output, /<runtime-data>\/cache\/state\.json/);
            assert.match(output, /<project-root>\\src\\main\.cjs:42:7/);
            assert.match(output, /<app-executable>\/Vantage\.exe:1:2/);
            assert.doesNotMatch(output, /C:[\\/]Users[\\/]Alice/i);
            assert.doesNotMatch(output, /D:[\\/]Projects[\\/]Vantage\+prod/i);
            assert.doesNotMatch(output, new RegExp(secret));
            assert.match(output, /api_key=\[REDACTED_API_KEY\]/);
        }
        assert.match(contents, /Stack: Symbol\(opaque\)/);
    } finally {
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
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

test('cleanup does not overwrite a log shortened after discovery', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_shrinking.log');
    const replacement = Buffer.from('shorter-current-content\n', 'utf8');
    const originalOpenSync = fs.openSync;
    const originalWriteSync = fs.writeSync;
    let mutationTriggered = false;
    let logger;

    try {
        fs.writeFileSync(logFile, 'old-content-'.repeat(80));
        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes: 128,
            maxFiles: 2,
        });

        fs.openSync = (file, flags, ...args) => {
            if (
                !mutationTriggered
                && path.resolve(file) === path.resolve(logFile)
                && flags === 'r'
            ) {
                mutationTriggered = true;
                const descriptor = originalOpenSync(logFile, 'w');
                try {
                    originalWriteSync(
                        descriptor,
                        replacement,
                        0,
                        replacement.length,
                        0,
                    );
                } finally {
                    fs.closeSync(descriptor);
                }
            }
            return originalOpenSync(file, flags, ...args);
        };

        logger.cleanup();
    } finally {
        fs.openSync = originalOpenSync;
    }

    try {
        assert.equal(mutationTriggered, true);
        assert.deepEqual(fs.readFileSync(logFile), replacement);
    } finally {
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('cleanup does not lose a tail appended after discovery', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_growing.log');
    const initial = Buffer.from('old-content-'.repeat(60), 'utf8');
    const appendedTail = Buffer.from('-new-concurrent-tail\n', 'utf8');
    const originalOpenSync = fs.openSync;
    const originalWriteSync = fs.writeSync;
    let mutationTriggered = false;
    let logger;

    try {
        fs.writeFileSync(logFile, initial);
        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes: 128,
            maxFiles: 2,
        });

        fs.openSync = (file, flags, ...args) => {
            if (
                !mutationTriggered
                && path.resolve(file) === path.resolve(logFile)
                && flags === 'r'
            ) {
                mutationTriggered = true;
                const descriptor = originalOpenSync(logFile, 'a');
                try {
                    originalWriteSync(
                        descriptor,
                        appendedTail,
                        0,
                        appendedTail.length,
                    );
                } finally {
                    fs.closeSync(descriptor);
                }
            }
            return originalOpenSync(file, flags, ...args);
        };

        logger.cleanup();
    } finally {
        fs.openSync = originalOpenSync;
    }

    try {
        assert.equal(mutationTriggered, true);
        assert.deepEqual(
            fs.readFileSync(logFile),
            Buffer.concat([initial, appendedTail]),
        );
    } finally {
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('cleanup skips replacement when an opened log grows during the tail read', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_read_race.log');
    const initial = Buffer.from('read-race-content-'.repeat(50), 'utf8');
    const appendedTail = Buffer.from('-appended-during-read\n', 'utf8');
    const originalOpenSync = fs.openSync;
    const originalReadSync = fs.readSync;
    const originalWriteSync = fs.writeSync;
    let mutationTriggered = false;
    let logger;

    try {
        fs.writeFileSync(logFile, initial);
        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes: 128,
            maxFiles: 2,
        });

        fs.readSync = (...args) => {
            const bytesRead = originalReadSync(...args);
            if (!mutationTriggered) {
                mutationTriggered = true;
                const descriptor = originalOpenSync(logFile, 'a');
                try {
                    originalWriteSync(
                        descriptor,
                        appendedTail,
                        0,
                        appendedTail.length,
                    );
                } finally {
                    fs.closeSync(descriptor);
                }
            }
            return bytesRead;
        };

        logger.cleanup();
    } finally {
        fs.readSync = originalReadSync;
    }

    try {
        assert.equal(mutationTriggered, true);
        assert.deepEqual(
            fs.readFileSync(logFile),
            Buffer.concat([initial, appendedTail]),
        );
    } finally {
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('cleanup verifies file identity again before replacing a legacy log', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_identity_race.log');
    const movedOriginal = path.join(tempDir, 'original-before-race.bin');
    const replacement = Buffer.from('new-file-at-original-path\n', 'utf8');
    const originalWriteFileSync = fs.writeFileSync;
    const originalRenameSync = fs.renameSync;
    let mutationTriggered = false;
    let logger;

    try {
        fs.writeFileSync(logFile, 'legacy-content-'.repeat(80));
        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes: 128,
            maxFiles: 2,
        });

        fs.writeFileSync = (file, data, options) => {
            const result = originalWriteFileSync(file, data, options);
            const name = path.basename(file);
            if (
                !mutationTriggered
                && name.startsWith(`.${path.basename(logFile)}.`)
                && name.endsWith('.tmp')
            ) {
                mutationTriggered = true;
                originalRenameSync(logFile, movedOriginal);
                originalWriteFileSync(logFile, replacement);
            }
            return result;
        };

        logger.cleanup();
    } finally {
        fs.writeFileSync = originalWriteFileSync;
    }

    try {
        assert.equal(mutationTriggered, true);
        assert.deepEqual(fs.readFileSync(logFile), replacement);
        assert.deepEqual(
            fs.readdirSync(tempDir).filter((name) => name.endsWith('.tmp')),
            [],
        );
    } finally {
        logger?.dispose?.();
        fs.rmSync(tempDir, { recursive: true, force: true });
    }
});

test('cleanup removes an incomplete UTF-8 code point from the legacy tail', () => {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-bounded-logger-'));
    const logFile = path.join(tempDir, 'electron_incomplete_utf8.log');
    const lastCompleteContent = '-最后完整内容\n';
    const incompleteCodePoint = Buffer.from([0xe6, 0xb1]);
    let logger;

    try {
        fs.writeFileSync(
            logFile,
            Buffer.concat([
                Buffer.from('old-prefix-'.repeat(50), 'utf8'),
                Buffer.from(lastCompleteContent, 'utf8'),
                incompleteCodePoint,
            ]),
        );
        logger = createBoundedLogger({
            logFile,
            consoleObject: silentConsole,
            maxBytes: 96,
            maxFiles: 2,
        });

        logger.cleanup();

        const contents = fs.readFileSync(logFile, 'utf8');
        assert.doesNotMatch(contents, /\uFFFD/);
        assert.match(contents, /-最后完整内容\n$/);
        assert.ok(fs.statSync(logFile).size <= 96);
    } finally {
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
