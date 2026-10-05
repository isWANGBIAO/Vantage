// Verify a packaged CLI without Electron's parent environment. All records use
// a temporary LOCALAPPDATA; no business tools are invoked and no faults induced.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createServer } = require('node:http');
const { setTimeout: delay } = require('node:timers/promises');

(async () => {
    const executable = path.resolve(process.argv[2] || '');
    assert.ok(process.argv[2] && fs.statSync(executable).isFile(), 'Pass a packaged backend executable.');
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vantage-packaged-diagnostics-'));
    const env = { ...process.env, LOCALAPPDATA: root };
    for (const key of Object.keys(env)) if (key.startsWith('VANTAGE_')) delete env[key];
    const requests = [];
    const server = createServer((request, response) => {
        requests.push(request.url);
        response.setHeader('Content-Type', 'application/json');
        response.end(JSON.stringify({ camera_online: false }));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const child = spawn(executable, ['--run-cli', '--base-url', `http://127.0.0.1:${server.address().port}`, 'mcp'], {
        cwd: path.dirname(executable), env, windowsHide: true, stdio: ['pipe', 'ignore', 'ignore'],
    });
    const exited = new Promise((resolve, reject) => {
        child.once('error', reject);
        child.once('exit', code => resolve(code));
    });
    const watchdog = setTimeout(() => child.kill(), 15000);
    const directory = path.join(root, 'Vantage', 'diagnostics', 'python');
    try {
        let record;
        for (let attempt = 0; attempt < 100 && !record; attempt += 1) {
            if (fs.existsSync(directory)) record = fs.readdirSync(directory).find(name => name.startsWith(`cli-${child.pid}-`) && name.endsWith('.active.log'));
            if (!record) await delay(100);
        }
        assert.ok(record, 'Standalone packaged CLI did not initialize diagnostics in user data.');
        child.stdin.end();
        assert.equal(await exited, 0, 'Isolated MCP must terminate normally at EOF.');
        assert.equal(fs.readdirSync(directory).length, 0, 'Clean empty diagnostic file must be removed.');
        assert.deepEqual(requests, ['/api/v1/system/status'], 'Only synthetic readiness may be queried.');
        console.log(JSON.stringify({ passed: true, standalonePackagedCli: true, userDataDirectory: true, cleanExit: true }));
    } finally {
        clearTimeout(watchdog);
        child.stdin.end();
        if (child.exitCode === null) child.kill();
        server.closeAllConnections();
        await new Promise(resolve => server.close(resolve));
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
