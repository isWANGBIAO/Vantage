// Explicit integration check: launches only the isolated demo with temporary user data.
const { _electron: electron } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
async function main() {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-desktop-'));
  const projectRoot = path.join(temporary, 'project'); await fs.mkdir(projectRoot);
  const env = { ...process.env, NEVER_STOP_DATA_DIR: path.join(temporary, 'data') }; delete env.ELECTRON_RUN_AS_NODE;
  const application = await electron.launch({ executablePath: process.env.NEVER_STOP_ELECTRON || require('electron'), args: [path.resolve(__dirname, '../main.cjs')], env, timeout: 30000 });
  try {
    if (process.env.NEVER_STOP_ELECTRON) {
      const packaged = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, path: app.getAppPath() }));
      assert.equal(packaged.packaged, true);
      assert.match(packaged.path, /app\.asar$/);
    }
    const page = await application.firstWindow();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.waitForLoadState('domcontentloaded');
    console.log('initial-page', await page.title(), (await page.locator('body').innerText()).slice(0, 1500));
    await page.screenshot({ path: path.join(temporary, 'initial.png') });
    await page.locator('#root').waitFor();
    const invoke = (method, payload) => page.evaluate(({ method, payload }) => window.neverStop.invoke(method, payload), { method, payload });
    const project = await invoke('project.add', { root: projectRoot, backend: 'codex' });
    const draft = await invoke('goal.read', { id: project.id });
    await invoke('goal.save', { id: project.id, text: '# 演示目标\n检查样例文件。', version: draft.version });
    await invoke('goal.publish', { id: project.id, text: '# 演示目标\n检查样例文件。' });
    assert.equal((await invoke('state')).projects[0].desiredRunning, false);
    await page.getByRole('button', { name: '目标 编辑、保存与发布' }).click();
    const editor = page.getByRole('textbox', { name: '目标 Markdown' });
    await editor.fill('# 尚未发布的草稿');
    await editor.press('Space');
    await editor.press('Control+s');
    await page.getByText('草稿已保存', { exact: true }).waitFor();
    assert.equal((await invoke('state')).projects[0].desiredRunning, false);
    assert.equal((await invoke('state')).projects[0].publishedGoal, '# 演示目标\n检查样例文件。');
    await editor.fill('# 本地未保存');
    await fs.writeFile(path.join(projectRoot, 'goal.md'), '# 外部修改');
    await editor.press('Control+s');
    await page.getByText('发现外部编辑冲突', { exact: true }).waitFor();
    assert.equal(await fs.readFile(path.join(projectRoot, 'goal.md'), 'utf8'), '# 外部修改');
    await page.getByRole('button', { name: '关闭目标', exact: true }).click();
    await fs.mkdir(path.join(projectRoot, '.never-stop'));
    await fs.writeFile(path.join(projectRoot, '.never-stop/progress.json'), JSON.stringify({ schema_version: 1, updated_at: new Date().toISOString(), overall_percent: 67, summary_markdown: '测试样例，非实际科研结果。', radar: { axes: [{ label: '实现', value: 80 }, { label: '测试', value: 65 }, { label: '说明', value: 56 }] }, suggestions_markdown: '核对目标后继续。' }));
    await page.getByText('67', { exact: false }).first().waitFor({ timeout: 10000 });
    await page.waitForTimeout(1200); // Let the chart's visual animation settle for the artifact.
    await page.screenshot({ path: path.join(temporary, 'demo.png'), fullPage: true });
    const before = await application.evaluate(({ BrowserWindow }) => { const w = BrowserWindow.getAllWindows()[0]; w.close(); return { id: w.id, visible: w.isVisible(), destroyed: w.isDestroyed() }; });
    assert.equal(before.visible, false); assert.equal(before.destroyed, false);
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].show());
    assert.equal((await invoke('state')).projects[0].id, project.id);
    const notification = await invoke('notifications.test');
    const secret = 'synthetic-desktop-credential-92846';
    const resource = await invoke('resources.save', { resource: { name: '本机测试资源', host: '127.0.0.1', username: 'test', password: secret } });
    assert.equal(resource.hasPassword, true);
    assert.equal(JSON.stringify(await invoke('state')).includes(secret), false);
    assert.equal((await fs.readFile(path.join(temporary, 'data', 'resources.json'), 'utf8')).includes(secret), false);
    await invoke('resources.remove', { id: resource.id });
    await invoke('project.remove', { id: project.id });
    assert.equal((await invoke('state')).projects.length, 0);
    assert.equal((await fs.stat(projectRoot)).isDirectory(), true);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ temporary, screenshot: path.join(temporary, 'demo.png'), uiErrors: errors, windowClosePreservedMain: true, platformCredentialEncryption: true, notification }, null, 2));
  } finally { await application.evaluate(({ app }) => app.exit(0)); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
