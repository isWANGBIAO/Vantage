import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, unlinkSync, rmSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import dependencySync from '../scripts/sync-dependencies.cjs';

const synchronizer = fileURLToPath(new URL('../scripts/sync-dependencies.cjs', import.meta.url));

test('real offline npm installation repairs removed CLI and runtime entries', (t) => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'vantage payload 中文 '));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const vendor = path.join(root, 'vendor');
  const app = path.join(root, 'app');
  mkdirSync(vendor);
  mkdirSync(app);
  const env = {
    ...process.env,
    npm_config_offline: 'true', npm_config_audit: 'false', npm_config_fund: 'false',
    npm_config_cache: path.join(root, 'cache'),
  };
  function run(command, args, cwd) {
    const execution = command === 'npm'
      ? dependencySync.resolveNpmExecution({ args, env })
      : { command, args };
    const result = spawnSync(execution.command, execution.args, {
      cwd, env, encoding: 'utf8', timeout: 30000,
    });
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    return result.stdout;
  }
  writeFileSync(path.join(vendor, 'package.json'), JSON.stringify({
    name: 'vantage-offline-toy', version: '1.0.0', main: 'index.cjs',
    bin: { 'vantage-offline-toy': 'cli.cjs' },
  }));
  writeFileSync(path.join(vendor, 'index.cjs'), 'module.exports = "fixture";');
  writeFileSync(path.join(vendor, 'cli.cjs'), '#!/usr/bin/env node\nconsole.log("fixture");');
  run('npm', ['pack', '--ignore-scripts'], vendor);
  writeFileSync(path.join(app, 'package.json'), JSON.stringify({
    name: 'vantage-offline-app', version: '1.0.0',
    dependencies: { 'vantage-offline-toy': 'file:../vendor/vantage-offline-toy-1.0.0.tgz' },
  }));
  run('npm', ['install', '--package-lock-only', '--ignore-scripts'], app);
  const sync = () => run(process.execPath, [synchronizer, '--webapp-root', app], app);
  assert.match(sync(), /dependencies synchronized/);
  assert.match(sync(), /already synchronized/);
  for (const name of ['cli.cjs', 'index.cjs']) {
    const target = path.join(app, 'node_modules/vantage-offline-toy', name);
    unlinkSync(target);
    run('npm', ['ls', '--depth=0'], app);
    assert.match(sync(), /dependencies synchronized/);
    assert.equal(existsSync(target), true);
    assert.match(run(process.execPath, ['-e', 'console.log(require("vantage-offline-toy"))'], app), /fixture/);
    assert.match(sync(), /already synchronized/);
  }
});
