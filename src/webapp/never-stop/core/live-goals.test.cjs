const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { Runner } = require('./runner.cjs');
const { Application } = require('./application.cjs');
const { ProjectFiles } = require('./files.cjs');

async function until(check) {
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw Error('inert recorder condition timed out');
}
async function fixture(t) {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-live-goals-')));
  const projectRoot = path.join(root, 'project');
  const dataDir = path.join(root, 'data');
  await fs.mkdir(projectRoot);
  const script = path.join(root, 'recorder.cjs');
  await fs.writeFile(script, `const fs=require('fs'); let prompt='';
process.stdin.on('data',c=>prompt+=c); process.stdin.on('end',()=>{
 const file='calls.jsonl'; const count=fs.existsSync(file)?fs.readFileSync(file,'utf8').trim().split('\\n').length:0;
 fs.appendFileSync(file,JSON.stringify({prompt})+'\\n');
 console.log(JSON.stringify({type:'thread.started',thread_id:'inert-session'}));
 setInterval(()=>{let release=0;try{release=Number(fs.readFileSync('release','utf8'));}catch{}
 if(release>count){console.log(JSON.stringify({type:'item.completed',item:{text:'inert complete'}}));process.exit(0);}},20);
});`);
  let runner;
  const make = async () => {
    runner = await new Runner({ dataDir, adapterFactory: () => ({ command: process.execPath, args: [script], backend: 'codex' }) }).init();
    const files = new ProjectFiles({ dataDir });
    const app = new Application({ runner, files, dataDir, resources: { list: () => [] } });
    await app.init();
    return { runner, app, files };
  };
  let current = await make();
  const project = await current.runner.addProject({ root: projectRoot, backend: 'codex' });
  const calls = async () => {
    try { return (await fs.readFile(path.join(projectRoot, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch { return []; }
  };
  const save = async text => {
    const disk = await current.app.invoke('goal.read', { id: project.id });
    return current.app.invoke('goal.save', { id: project.id, text, version: disk.version });
  };
  const restart = async () => {
    await current.runner.shutdown({ preserveIntent: true });
    current = await make();
    return current;
  };
  t.after(async () => { await runner.shutdown(); await fs.rm(root, { recursive: true, force: true }); });
  return { ...current, project, projectRoot, calls, save, restart, release: n => fs.writeFile(path.join(projectRoot, 'release'), String(n)) };
}

test('saving goal.md starts without publishing and ignores legacy snapshots', async t => {
  const f = await fixture(t);
  await f.save('saved live target');
  await f.runner.start(f.project.id);
  await until(async () => (await f.calls()).length === 1);
  const prompt = (await f.calls())[0].prompt;
  assert.match(prompt, /saved live target/);
  assert.doesNotMatch(prompt, /当前已发布目标|文件缺失时使用以下快照/);
});

test('save does not interrupt current invocation; next turns read saved and external goals', async t => {
  const f = await fixture(t);
  await f.save('first unique target');
  await f.runner.start(f.project.id);
  await until(async () => (await f.calls()).length === 1);
  const owner = f.runner.snapshot()[0];
  const saved = await f.save('second unique target');
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal((await f.calls()).length, 1);
  assert.equal(f.runner.snapshot()[0].adoptedGoalVersion, owner.adoptedGoalVersion);
  await f.release(1);
  await until(async () => (await f.calls()).length === 2);
  assert.match((await f.calls())[1].prompt, /second unique target/);
  assert.doesNotMatch((await f.calls())[1].prompt, /first unique target/);
  assert.equal(f.runner.snapshot()[0].adoptedGoalVersion, saved.version);
  await fs.writeFile(path.join(f.projectRoot, 'goal.md'), 'external third target');
  await f.release(2);
  await until(async () => (await f.calls()).length === 3);
  assert.match((await f.calls())[2].prompt, /external third target/);
  assert.doesNotMatch((await f.calls())[2].prompt, /second unique target/);
});

test('reset and restart use current file, not the legacy published snapshot', async t => {
  const f = await fixture(t);
  await f.save('initial target');
  await f.runner.start(f.project.id);
  await until(async () => (await f.calls()).length === 1);
  await fs.writeFile(path.join(f.projectRoot, 'goal.md'), 'reset target');
  await f.runner.reset(f.project.id);
  await until(async () => (await f.calls()).length === 2);
  assert.match((await f.calls())[1].prompt, /reset target/);
  await fs.writeFile(path.join(f.projectRoot, 'goal.md'), 'restarted target');
  await f.restart();
  await until(async () => (await f.calls()).length === 3);
  assert.match((await f.calls())[2].prompt, /restarted target/);
  assert.doesNotMatch((await f.calls())[2].prompt, /reset target/);
});

for (const invalid of ['missing', 'empty', 'whitespace', 'bad-utf8', 'oversized', 'directory']) {
  test(`invalid ${invalid} goal cannot start even with a legacy snapshot`, async t => {
    const f = await fixture(t);
    const goal = path.join(f.projectRoot, 'goal.md');
    if (invalid === 'directory') await fs.mkdir(goal);
    else if (invalid !== 'missing') await fs.writeFile(goal, {
      empty: '', whitespace: ' \n\t', 'bad-utf8': Buffer.from([0xff]), oversized: 'x'.repeat(1024 * 1024 + 1),
    }[invalid]);
    f.runner.projects[0].publishedGoal = 'stale legacy target';
    await assert.rejects(f.runner.start(f.project.id), /goal\.md/);
    assert.equal((await f.calls()).length, 0);
    assert.equal(f.runner.snapshot()[0].desiredRunning, false);
  });
}

test('unreadable goal is rejected with no sensitive OS error or child launch', async t => {
  const f = await fixture(t);
  await f.save('valid target');
  const open = fs.open;
  fs.open = async (file, ...args) => {
    if (file === path.join(f.projectRoot, 'goal.md')) throw Object.assign(Error('synthetic-private-detail'), { code: 'EACCES' });
    return open(file, ...args);
  };
  try {
    await assert.rejects(f.runner.start(f.project.id), error => {
      assert.match(error.message, /goal\.md/);
      assert.doesNotMatch(error.message, /synthetic-private-detail/);
      return true;
    });
    assert.equal((await f.calls()).length, 0);
  } finally { fs.open = open; }
});

test('a goal that becomes invalid pauses before another invocation', async t => {
  const f = await fixture(t);
  await f.save('valid target');
  await f.runner.start(f.project.id);
  await until(async () => (await f.calls()).length === 1);
  await fs.writeFile(path.join(f.projectRoot, 'goal.md'), ' ');
  await f.release(1);
  await until(() => f.runner.snapshot()[0].desiredRunning === false);
  assert.equal((await f.calls()).length, 1);
  assert.match(f.runner.snapshot()[0].error.message, /goal\.md/);
});

test('paused reset clears the previously adopted goal version', async t => {
  const f = await fixture(t);
  f.runner.projects[0].adoptedGoalVersion = 'old invocation';
  await f.runner.reset(f.project.id);
  assert.equal(f.runner.snapshot()[0].adoptedGoalVersion, null);
});

test('concurrent legacy publication preserves call order in the authoritative file', async t => {
  const f = await fixture(t);
  const write = fs.writeFile;
  fs.writeFile = async (file, text, ...args) => {
    if (text === 'obsolete') await new Promise(resolve => setTimeout(resolve, 40));
    return write(file, text, ...args);
  };
  try {
    await Promise.all([f.runner.publish(f.project.id, 'obsolete'), f.runner.publish(f.project.id, 'latest')]);
    assert.equal(await fs.readFile(path.join(f.projectRoot, 'goal.md'), 'utf8'), 'latest');
  } finally { fs.writeFile = write; }
});
