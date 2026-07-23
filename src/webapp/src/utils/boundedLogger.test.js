import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import boundedLogger from './boundedLogger.cjs';

const { createBoundedLogger } = boundedLogger;

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
