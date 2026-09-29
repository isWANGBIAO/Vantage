const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(predicate, timeout = 7000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(20);
  }
  assert.fail("Expected live output before the held CLI completes");
}

async function fixture(t, { flood = false, partialOnly = false } = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-live-"));
  const script = path.join(dir, "fake-output.cjs");
  await fs.writeFile(
    script,
    `
const fs = require('node:fs');
const path = require('node:path');
const backend = process.argv[2];
const suffix = path.basename(process.cwd());
const secret = process.env.NEVER_STOP_RESOURCE_TOKEN || '';
const emit = (value) => process.stdout.write(JSON.stringify(value) + '\\n');
let prompt = '';
process.stdin.on('data', (chunk) => prompt += chunk);
process.stdin.resume();
process.stdin.on('end', () => {
  fs.writeFileSync('held-cli.pid', String(process.pid));
  if (backend === 'claude') {
    emit({type:'system',subtype:'init',session_id:'claude-owned-'+suffix});
    if (${JSON.stringify(partialOnly)}) {
      emit({type:'stream_event',event:{type:'content_block_delta',index:0,delta:{type:'thinking_delta',thinking:'PRIVATE_THINKING '+secret}}});
      setInterval(()=>{},1000);
      return;
    }
    emit({type:'assistant',message:{content:[{type:'text',text:'CLAUDE_LIVE_'+suffix+' '+secret},{type:'tool_use',id:'tool-1',name:'Bash',input:{command:'pwd'}}]}});
    emit({type:'user',message:{content:[{type:'tool_result',tool_use_id:'tool-1',content:'CLAUDE_TOOL_RESULT_'+suffix+' '+secret}]}});
  } else {
    emit({type:'thread.started',thread_id:'codex-owned-'+suffix});
    emit({type:'item.started',item:{id:'tool-1',type:'command_execution',command:'pwd',status:'in_progress'}});
    emit({type:'item.completed',item:{id:'tool-1',type:'command_execution',command:'pwd',aggregated_output:'CODEX_TOOL_RESULT_'+suffix+' '+secret,exit_code:0,status:'completed'}});
    emit({type:'item.completed',item:{id:'answer-1',type:'agent_message',text:'CODEX_LIVE_'+suffix+' '+secret}});
  }
  if (fs.existsSync('fake-resource-response')) {
    const credential = fs.readFileSync('fake-resource-response', 'utf8');
    fs.writeFileSync('credential-input-check.json', JSON.stringify({inPrompt:prompt.includes(credential),inEnvironment:Object.values(process.env).some(value=>value.includes(credential))}));
    emit({type:'item.completed',item:{id:'callback-secret',type:'agent_message',text:'CALLBACK_RESOURCE '+credential}});
    for (const offset of [480,980,1980,3980,7980]) emit({type:'item.completed',item:{id:'boundary-'+offset,type:'agent_message',text:'BOUNDARY'+'x'.repeat(offset)+credential}});
  }
  if (${JSON.stringify(flood)}) {
    for (let i=0;i<50000;i++) emit({type:'item.completed',item:{id:'flood-'+i,type:'agent_message',text:'FLOOD_'+i+' '+secret}});
    fs.writeFileSync('flood-produced', '50000');
  }
  setInterval(() => {}, 1000);
});
`,
  );
  const secrets = new Map();
  const credentials = new Map();
  const runner = new Runner({
    dataDir: path.join(dir, "data"),
    principles: "Fixed execution principles",
    adapterFactory: (project) => ({
      command: process.execPath,
      args: [script, project.backend],
      backend: project.backend,
    }),
    executionEnv: async (project) => ({
      NEVER_STOP_RESOURCE_TOKEN: secrets.get(project.id) || "",
    }),
    outputSecrets: async (project) =>
      credentials.has(project.id) ? [credentials.get(project.id)] : [],
  });
  await runner.init();
  t.after(async () => {
    await runner.shutdown();
    await fs.rm(dir, { recursive: true, force: true });
  });
  async function add(name, backend) {
    const root = path.join(dir, name);
    await fs.mkdir(root);
    const project = await runner.addProject({ root, backend });
    await runner.publish(project.id, "Safe sample goal");
    secrets.set(project.id, "private-runtime-value-" + name + "-0123456789");
    return project;
  }
  return { runner, dir, add, secrets, credentials };
}

test('partial thinking is visible as safe activity before any complete assistant block or process exit', async t => {
  const { runner, add, secrets } = await fixture(t, { partialOnly: true });
  const project = await add('partial', 'claude');
  const received = [];
  runner.on('output', (id, entries) => { if (id === project.id) received.push(...entries); });
  await runner.start(project.id);
  await until(() => received.some(entry => /模型正在思考/.test(entry.text)));
  const pid = Number(await fs.readFile(path.join(project.root, 'held-cli.pid'), 'utf8'));
  assert.equal(process.kill(pid, 0), true);
  assert.ok(!received.some(entry => entry.kind === 'assistant'));
  assert.ok(!JSON.stringify(received).includes('PRIVATE_THINKING'));
  assert.ok(!JSON.stringify(received).includes(secrets.get(project.id)));
  await runner.pause(project.id);
});

for (const backend of ["claude", "codex"]) {
  test(
    backend +
      " text and tool output arrive before the held process exits, without persistence or secrets",
    async (t) => {
      const { runner, dir, add, secrets } = await fixture(t);
      const project = await add("sample", backend);
      const received = [];
      runner.on("output", (id, entries) => {
        assert.equal(id, project.id);
        assert.ok(Array.isArray(entries));
        for (const entry of entries) {
          assert.equal(typeof entry.text, "string");
          assert.equal(typeof entry.kind, "string");
          assert.ok(entry.kind.length > 0);
          received.push(entry);
        }
      });
      await runner.start(project.id);
      const prefix = backend.toUpperCase();
      await until(
        () =>
          received.some((e) => e.text.includes(prefix + "_LIVE_sample")) &&
          received.some((e) => e.text.includes(prefix + "_TOOL_RESULT_sample")),
      );
      const cliPid = Number(
        await fs.readFile(path.join(project.root, "held-cli.pid"), "utf8"),
      );
      assert.equal(
        process.kill(cliPid, 0),
        true,
        "CLI must still be executing when output is visible",
      );
      assert.equal(runner.snapshot()[0].desiredRunning, true);
      assert.ok(
        received.some((e) => /pwd|Bash/.test(e.text)),
        "Tool invocation is represented",
      );
      assert.ok(
        !JSON.stringify(received).includes(secrets.get(project.id)),
        "Raw runtime token must not reach the renderer",
      );
      await runner.pause(project.id);
      const persisted = await fs.readFile(
        path.join(dir, "data", "projects.json"),
        "utf8",
      );
      assert.ok(!persisted.includes(prefix + "_LIVE_sample"));
      assert.ok(!persisted.includes(prefix + "_TOOL_RESULT_sample"));
      assert.ok(!persisted.includes(secrets.get(project.id)));
    },
  );
}

test("simultaneous live outputs retain the owning project ID", async (t) => {
  const { runner, add } = await fixture(t);
  const a = await add("projectA", "claude");
  const b = await add("projectB", "codex");
  const textById = new Map();
  runner.on("output", (id, entries) =>
    textById.set(
      id,
      (textById.get(id) || "") + entries.map((e) => e.text).join("\n"),
    ),
  );
  await Promise.all([runner.start(a.id), runner.start(b.id)]);
  await until(
    () =>
      textById.get(a.id)?.includes("CLAUDE_LIVE_projectA") &&
      textById.get(b.id)?.includes("CODEX_LIVE_projectB"),
  );
  assert.ok(!textById.get(a.id).includes("CODEX_LIVE_projectB"));
  assert.ok(!textById.get(b.id).includes("CLAUDE_LIVE_projectA"));
  await runner.pause(a.id);
  assert.equal(
    runner.snapshot().find((p) => p.id === b.id).desiredRunning,
    true,
  );
});

test("50000 live records remain bounded and pause remains responsive", async (t) => {
  const { runner, dir, add, secrets } = await fixture(t, { flood: true });
  const project = await add("flood", "codex");
  let batches = 0,
    entriesSeen = 0,
    largestBatch = 0,
    largestText = 0,
    leaked = false;
  runner.on("output", (id, entries) => {
    assert.equal(id, project.id);
    batches++;
    entriesSeen += entries.length;
    largestBatch = Math.max(
      largestBatch,
      Buffer.byteLength(JSON.stringify(entries)),
    );
    for (const entry of entries) {
      largestText = Math.max(largestText, entry.text.length);
      if (entry.text.includes(secrets.get(project.id))) leaked = true;
    }
  });
  await runner.start(project.id);
  await until(async () => {
    try {
      await fs.access(path.join(project.root, "flood-produced"));
      return entriesSeen > 0;
    } catch {
      return false;
    }
  }, 15000);
  await delay(150);
  const started = Date.now();
  await runner.pause(project.id);
  assert.ok(
    Date.now() - started < 5000,
    "Pause must not drain an unbounded log queue",
  );
  assert.ok(
    batches < 2000,
    "High-frequency records are batched rather than emitting one IPC call per line",
  );
  assert.ok(
    largestBatch <= 1024 * 1024,
    "Each renderer payload has a finite size cap",
  );
  assert.ok(
    largestText <= 65536,
    "Each individual display entry has a finite size cap",
  );
  assert.equal(leaked, false);
  const persisted = await fs.readFile(
    path.join(dir, "data", "projects.json"),
    "utf8",
  );
  assert.ok(!persisted.includes("FLOOD_"));
});

test("callback-only resource credentials are filtered before entry truncation without entering prompt or CLI environment", async (t) => {
  const { runner, dir, add, credentials } = await fixture(t);
  const project = await add("credential", "codex");
  const secret = "boundarycredential-raw-value-0123456789abcdef";
  credentials.set(project.id, secret);
  await fs.writeFile(path.join(project.root, "fake-resource-response"), secret);
  const received = [];
  runner.on("output", (id, entries) => {
    if (id === project.id) received.push(...entries);
  });
  await runner.start(project.id);
  await until(
    () =>
      received.some((entry) => entry.text.includes("CALLBACK_RESOURCE")) &&
      received.some((entry) => entry.text.includes("BOUNDARY")),
  );
  await runner.pause(project.id);
  assert.ok(
    !JSON.stringify(received).includes(secret.slice(0, 8)),
    "No truncated fragment of the raw credential may escape filtering",
  );
  const inputs = JSON.parse(
    await fs.readFile(
      path.join(project.root, "credential-input-check.json"),
      "utf8",
    ),
  );
  assert.deepEqual(inputs, { inPrompt: false, inEnvironment: false });
  assert.ok(
    !(
      await fs.readFile(path.join(dir, "data", "projects.json"), "utf8")
    ).includes(secret),
  );
});
