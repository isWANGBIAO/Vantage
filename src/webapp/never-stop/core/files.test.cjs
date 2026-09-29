const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { ProjectFiles, validateProgress } = require('./files.cjs');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-files-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return { root, files: new ProjectFiles() };
}
function progress() {
  return { schema_version: 1, updated_at: '2026-09-12T12:00:00+08:00', overall_percent: 100,
    summary_markdown: '最新状态', radar: { axes: [{ label: '正确性', value: 100 }, { label: '速度', value: 60 }, { label: '文档', value: 20 }] }, suggestions_markdown: '建议' };
}
test('draft saves detect external conflicts and never create a published snapshot', async t => {
  const { root, files } = await fixture(t);
  const first = await files.readGoal(root);
  await files.saveGoal(root, 'draft', first.version);
  const edited = await files.readGoal(root);
  await fs.writeFile(path.join(root, 'goal.md'), 'external');
  await assert.rejects(files.saveGoal(root, 'local', edited.version), /冲突/);
  assert.equal((await files.readGoal(root)).text, 'external');
  assert.deepEqual(await fs.readdir(root), ['goal.md']);
});
test('first invalid snapshot preserves existing progress then valid JSON deterministically replaces it', async t => {
  const { root, files } = await fixture(t);
  await fs.writeFile(path.join(root, 'progress.md'), 'existing notes');
  assert.equal((await files.readProgress(root)).markdown, 'existing notes');
  await fs.mkdir(path.join(root, '.never-stop'));
  const file = path.join(root, '.never-stop/progress.json');
  await fs.writeFile(file, '{');
  assert.equal((await files.readProgress(root)).markdown, 'existing notes');
  await fs.writeFile(file, JSON.stringify(progress()));
  const valid = await files.readProgress(root);
  assert.equal(valid.snapshot.overall_percent, 100);
  assert.match(valid.markdown, /Agent 自评/);
  await fs.writeFile(file, JSON.stringify({ ...progress(), overall_percent: 101 }));
  const invalid = await files.readProgress(root);
  assert.deepEqual(invalid.snapshot, valid.snapshot);
  assert.equal(invalid.markdown, valid.markdown);
  assert.ok(invalid.error);
});
test('display protocol rejects coercion, illegal scores, timestamps without offset and invalid axes', () => {
  for (const patch of [{ overall_percent: '20' }, { overall_percent: -1 }, { updated_at: '2026-01-01' }, { radar: { axes: [{ label: 'a', value: null }] } }, { schema_version: true }]) {
    assert.throws(() => validateProgress({ ...progress(), ...patch }));
  }
  assert.doesNotThrow(() => validateProgress({ ...progress(), overall_percent: null, radar: { axes: [] } }));
});
test('generated Markdown is restored from last valid snapshot after file changes', async t => {
  const { root, files } = await fixture(t);
  await fs.mkdir(path.join(root, '.never-stop'));
  await fs.writeFile(path.join(root, '.never-stop/progress.json'), JSON.stringify(progress()));
  const valid = await files.readProgress(root);
  await fs.writeFile(path.join(root, 'progress.md'), 'accidental overwrite');
  assert.equal((await files.readProgress(root)).markdown, valid.markdown);
  assert.equal(await fs.readFile(path.join(root, 'progress.md'), 'utf8'), valid.markdown);
});
