const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { ResourceStore, startResourceBroker } = require("../core/resources.cjs");
const { requestResource } = require("../core/resource-helper.cjs");
const { discoverProjects } = require("../core/discovery.cjs");
const { DailyNotifier } = require("../core/notifications.cjs");
const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (s) => Buffer.from(s).map((x) => x ^ 177),
  decryptString: (b) =>
    Buffer.from(b)
      .map((x) => x ^ 177)
      .toString(),
};
async function temp(t) {
  const p = await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-services-"));
  t.after(() => fs.rm(p, { recursive: true, force: true }));
  return p;
}
test("resources persist encrypted, list and prompt exclude secrets, broker authorizes selected ids", async (t) => {
  const dataDir = await temp(t);
  const store = new ResourceStore({ dataDir, safeStorage });
  await store.init();
  const item = await store.save({
    alias: "test",
    host: "localhost",
    username: "user",
    password: "TEST_SECRET",
  });
  assert.equal(item.hasPassword, true);
  assert.equal(item.password, undefined);
  assert.ok(
    !(await fs.readFile(path.join(dataDir, "resources.json"), "utf8")).includes(
      "TEST_SECRET",
    ),
  );
  assert.ok(!store.prompt([item.id]).includes("TEST_SECRET"));
  const again = new ResourceStore({ dataDir, safeStorage });
  await again.init();
  assert.equal(again.list().length, 1);
  let used;
  const broker = await startResourceBroker(store, {
    allowedIds: [item.id],
    execute: async (resource, command) => {
      used = { resource, command };
      return { stdout: "worked", stderr: "", code: 0 };
    },
  });
  t.after(() => broker.close());
  const result = await requestResource(
    { id: item.id, command: "echo ok" },
    broker.env,
  );
  assert.equal(result.stdout, "worked");
  assert.equal(used.resource.password, "TEST_SECRET");
  await assert.rejects(
    requestResource({ id: "unselected", command: "x" }, broker.env),
    /未选择/,
  );
  await assert.rejects(
    requestResource(
      { id: item.id, command: "x" },
      { ...broker.env, NEVER_STOP_RESOURCE_TOKEN: "bad" },
    ),
    /授权/,
  );
  await store.remove(item.id);
  assert.deepEqual(store.list(), []);
});
test("secrets fail closed without platform encryption; SSH import reports unsupported Include", async (t) => {
  const home = await temp(t);
  const store = new ResourceStore({
    dataDir: home,
    safeStorage: { isEncryptionAvailable: () => false },
    home,
  });
  await store.init();
  await assert.rejects(
    store.save({ host: "host", password: "secret" }),
    /安全存储/,
  );
  await fs.mkdir(path.join(home, ".ssh"));
  await fs.writeFile(
    path.join(home, ".ssh/config"),
    "Include parts/*\nHost example\n HostName server\n User tester\n Port 2222\n IdentityFile ~/.ssh/id_ed25519\nHost *\n User ignored\n",
  );
  const result = await store.importSSH();
  assert.equal(result.resources[0].port, 2222);
  assert.ok(result.warnings.some((x) => x.includes("Include")));
});
test("discovery reads only bounded known metadata and warns on unavailable formats", async (t) => {
  const home = await temp(t);
  const project = path.join(home, "project");
  await fs.mkdir(project);
  await fs.writeFile(
    path.join(home, ".claude.json"),
    JSON.stringify({ projects: { [project]: {} } }),
  );
  await fs.mkdir(path.join(home, ".codex/sessions/2026/09/12"), {
    recursive: true,
  });
  await fs.writeFile(
    path.join(home, ".codex/sessions/2026/09/12/rollout-test.jsonl"),
    JSON.stringify({ type: "session_meta", payload: { cwd: project } }) +
      "\nPRIVATE CONVERSATION",
  );
  const found = await discoverProjects({ home });
  assert.ok(
    found.projects.some(
      (x) => x.root === project && x.source.includes("Codex"),
    ),
  );
  assert.ok(
    found.projects.some(
      (x) => x.root === project && x.source.includes("Claude"),
    ),
  );
  await fs.writeFile(path.join(home, ".claude.json"), "bad");
  assert.ok(
    (await discoverProjects({ home })).warnings.some((x) =>
      x.includes("Claude"),
    ),
  );
});
test("daily native notifications distinguish retrying and exclude paused once per local day", async () => {
  const shown = [];
  let opened;
  class Notification {
    static isSupported() {
      return true;
    }
    constructor(opts) {
      this.opts = opts;
    }
    on(event, cb) {
      this[event] = cb;
    }
    show() {
      shown.push(this);
    }
  }
  const state = {};
  let saves = 0;
  const notifier = new DailyNotifier({
    Notification,
    loadState: () => state,
    saveState: async (s) => {
      Object.assign(state, s);
      saves++;
    },
    onOpen: (id) => {
      opened = id;
    },
  });
  const projects = [
    { id: "a", name: "A", desiredRunning: true, status: "running" },
    { id: "b", name: "B", desiredRunning: true, status: "retrying" },
    { id: "c", name: "C", desiredRunning: false, status: "paused" },
  ];
  await notifier.tick(
    { enabled: true, time: "09:00" },
    projects,
    new Date(2026, 8, 12, 9, 0),
  );
  await notifier.tick(
    { enabled: true, time: "09:00" },
    projects,
    new Date(2026, 8, 12, 10, 0),
  );
  assert.equal(shown.length, 2);
  assert.match(shown[1].opts.body, /重试/);
  shown[0].click();
  assert.equal(opened, "a");
  assert.equal(saves, 1);
  await notifier.tick(
    { enabled: true, time: "09:00" },
    projects,
    new Date(2026, 8, 13, 9, 0),
  );
  assert.equal(shown.length, 4);
});
test("credential text is redacted from helper output and repeated errors", async (t) => {
  const store = new ResourceStore({ dataDir: await temp(t), safeStorage });
  await store.init();
  const item = await store.save({ host: "local", password: "do-not-log-this" });
  const broker = await startResourceBroker(store, {
    allowedIds: () => [item.id],
    execute: async () => ({
      stdout: "do-not-log-this",
      stderr: "do-not-log-this",
      code: 0,
    }),
  });
  t.after(() => broker.close());
  const result = await requestResource(
    { id: item.id, command: "run" },
    broker.env,
  );
  assert.ok(!JSON.stringify(result).includes("do-not-log-this"));
});
test("unsupported notifications return truthful error without marking as delivered", async () => {
  let persisted = false;
  const notifier = new DailyNotifier({
    Notification: { isSupported: () => false },
    saveState: async () => {
      persisted = true;
    },
  });
  await notifier.tick(
    { enabled: true, time: "09:00" },
    [{ id: "a", desiredRunning: true }],
    new Date(2026, 8, 12, 9, 0),
  );
  assert.match(notifier.error, /通知/);
  assert.equal(persisted, false);
});
test("actual helper subprocess authenticates via local SSH server with encrypted password and trusted host key", async (t) => {
  const { Server, utils } = require("ssh2");
  const { spawn } = require("node:child_process");
  const home = await temp(t);
  // OpenSSH key generation uses the system tool, matching the production known_hosts requirement.
  const { promisify } = require("node:util");
  await promisify(require("node:child_process").execFile)(
    "ssh-keygen",
    ["-q", "-t", "ed25519", "-N", "", "-f", path.join(home, "hostkey")],
    { windowsHide: true },
  );
  const hostKey = await fs.readFile(path.join(home, "hostkey"));
  const parsed = utils.parseKey(hostKey);
  let authenticated = false;
  const server = new Server({ hostKeys: [hostKey] }, (client) => {
    client.on("error", () => {});
    client.on("authentication", (ctx) => {
      if (
        ctx.method === "password" &&
        ctx.username === "tester" &&
        ctx.password === "local-test-secret"
      ) {
        authenticated = true;
        ctx.accept();
      } else ctx.reject();
    });
    client.on("ready", () =>
      client.on("session", (accept) => {
        const session = accept();
        session.on("exec", (acceptExec, _reject, info) => {
          const stream = acceptExec();
          stream.write(`ran: ${info.command}`);
          stream.exit(0);
          stream.end();
        });
      }),
    );
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const port = server.address().port;
  await fs.mkdir(path.join(home, ".ssh"));
  await fs.writeFile(
    path.join(home, ".ssh/known_hosts"),
    `[127.0.0.1]:${port} ${parsed.type} ${parsed.getPublicSSH().toString("base64")}\n`,
  );
  const store = new ResourceStore({ dataDir: home, safeStorage, home });
  await store.init();
  const resource = await store.save({
    host: "127.0.0.1",
    port,
    username: "tester",
    password: "local-test-secret",
  });
  const broker = await startResourceBroker(store, {
    allowedIds: [resource.id],
  });
  t.after(() => broker.close());
  const child = spawn(
    process.execPath,
    [path.join(__dirname, "../core/resource-helper.cjs")],
    { env: { ...process.env, ...broker.env }, windowsHide: true },
  );
  let output = "";
  let error = "";
  child.stdout.on("data", (x) => {
    output += x;
  });
  child.stderr.on("data", (x) => {
    error += x;
  });
  child.stdin.end(
    JSON.stringify({ id: resource.id, command: "echo isolated" }),
  );
  const code = await new Promise((resolve) => child.on("close", resolve));
  assert.equal(code, 0, error);
  assert.equal(output, "ran: echo isolated");
  assert.equal(authenticated, true);
  assert.ok(!output.includes("local-test-secret"));
  await fs.writeFile(path.join(home, ".ssh/known_hosts"), "");
  await assert.rejects(
    requestResource({ id: resource.id, command: "echo rejected" }, broker.env),
    /信任/,
  );
});
test("resource editing uses displayed name and preserves encrypted password when blank", async (t) => {
  const store = new ResourceStore({ dataDir: await temp(t), safeStorage });
  await store.init();
  const item = await store.save({
    name: "before",
    host: "local",
    password: "kept-secret",
  });
  const updated = await store.save({ ...item, name: "after", password: "" });
  assert.equal(updated.name, "after");
  assert.equal(store.credential(item.id).password, "kept-secret");
  await store.save({ ...updated, clearPassword: true });
  assert.equal(store.list()[0].hasPassword, false);
});
