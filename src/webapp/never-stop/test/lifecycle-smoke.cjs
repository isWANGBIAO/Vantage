// Explicit Windows Electron lifecycle check. No configured model is contacted:
// the only discoverable Claude executable is a hard link to this Node runtime.
// Run with PLAYWRIGHT_MODULE pointing to an installed Playwright package when
// Playwright is supplied by the host rather than the repository.
const { _electron: electron } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright",
);
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const assert = require("node:assert/strict");
const { terminateOwned } = require("../core/process-owner.cjs");

const delay = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
async function until(read, predicate, label, timeout = 30000) {
  const started = Date.now();
  let current;
  while (Date.now() - started < timeout) {
    current = await read();
    if (predicate(current)) return current;
    await delay(40);
  }
  throw new Error(`${label}: timed out; last value ${JSON.stringify(current)}`);
}
async function exitApplication(application) {
  if (!application || application.process().exitCode !== null) return;
  const exited = new Promise((resolve) =>
    application.process().once("exit", resolve),
  );
  await application.evaluate(({ app }) => app.exit(0));
  await exited;
}

async function main() {
  assert.equal(
    process.platform,
    "win32",
    "This lifecycle scenario validates Windows only",
  );
  const temporary = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-lifecycle-"),
  );
  const dataDir = path.join(temporary, "data");
  const projectRoot = path.join(temporary, "project");
  const bin = path.join(temporary, "bin");
  await fs.mkdir(projectRoot);
  await fs.mkdir(bin);
  const substitute = path.join(bin, "claude.exe");
  await fs.link(process.execPath, substitute);
  assert.equal(
    (await fs.stat(process.execPath)).ino,
    (await fs.stat(substitute)).ino,
  );
  const env = { ...process.env, NEVER_STOP_DATA_DIR: dataDir };
  // Avoid differently cased PATH entries competing in Windows child environments.
  for (const key of Object.keys(env))
    if (key.toLowerCase() === "path") delete env[key];
  env.PATH = `${bin}${path.delimiter}${process.env.PATH || process.env.Path || ""}`;
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;
  delete env.NODE_PATH;
  const uiErrors = [];
  const launches = [];
  let application;
  let projectId;
  const launch = async () => {
    application = await electron.launch({
      executablePath: process.env.NEVER_STOP_ELECTRON || require("electron"),
      args: [path.resolve(__dirname, "../main.cjs")],
      env,
      timeout: 30000,
    });
    launches.push(application.process().pid);
    const page = await application.firstWindow();
    page.on("pageerror", (error) => uiErrors.push(error.message));
    await page.waitForFunction(
      () => typeof window.neverStop?.invoke === "function",
    );
    const invoke = (method, payload) =>
      page.evaluate(
        ({ method, payload }) => window.neverStop.invoke(method, payload),
        { method, payload },
      );
    const readProject = async () =>
      (await invoke("state")).projects.find(
        (project) => project.id === projectId,
      );
    return { page, invoke, readProject };
  };
  const saved = async () =>
    JSON.parse(await fs.readFile(path.join(dataDir, "projects.json"), "utf8"));
  const report = {
    platform: process.platform,
    temporary,
    launches,
    fakeAgent: "node.exe hard-linked as claude.exe",
  };
  try {
    let client = await launch();
    const created = await client.invoke("project.add", {
      root: projectRoot,
      backend: "claude",
    });
    projectId = created.id;
    const draft = await client.invoke("goal.read", { id: projectId });
    const text =
      "# Lifecycle fixture\nDo not perform model work. The fixture executable only rejects CLI flags.";
    await client.invoke("goal.save", {
      id: projectId,
      text,
      version: draft.version,
    });
    await client.invoke("goal.publish", { id: projectId, text });
    await client.invoke("project.start", { id: projectId });
    const failed = await until(
      client.readProject,
      (project) => project.error?.count >= 6,
      "six controlled failures",
      60000,
    );
    assert.equal(failed.desiredRunning, true);
    assert.match(
      failed.error.message,
      /bad option|unknown option|invalid option/i,
    );
    assert.ok(
      failed.error.message.includes(substitute),
      "failure must identify the temporary fake executable",
    );
    report.failuresBeforeHide = failed.error.count;
    const hidden = await application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0];
      window.close();
      return { visible: window.isVisible(), destroyed: window.isDestroyed() };
    });
    assert.deepEqual(hidden, { visible: false, destroyed: false });
    const continued = await until(
      client.readProject,
      (project) => project.error?.count >= failed.error.count + 2,
      "hidden-window retry continuation",
      30000,
    );
    report.failuresWhileHidden = continued.error.count;
    assert.equal(continued.desiredRunning, true);
    // Crash between quick failures, when no unknown-session invocation is in flight.
    // This isolates persisted intent restoration from the separate uncertain-session guard.
    const countBeforeRestart = continued.error.count;
    const crashExit = new Promise((resolve) =>
      application.process().once("exit", resolve),
    );
    // Observe and exit in the same main-process callback, without an IPC round trip
    // between the idle observation and the crash itself.
    await application
      .evaluate(
        ({ app }, statePath) =>
          new Promise((resolve, reject) => {
            const fileSystem = process.getBuiltinModule("fs");
            const started = Date.now();
            const timer = setInterval(() => {
              try {
                const project = JSON.parse(
                  fileSystem.readFileSync(statePath, "utf8"),
                )[0];
                if (project.status === "retrying" && !project.owner) {
                  clearInterval(timer);
                  resolve();
                  app.exit(0);
                } else if (Date.now() - started > 30000) {
                  clearInterval(timer);
                  reject(new Error("No idle retry window observed for crash"));
                }
              } catch (error) {
                clearInterval(timer);
                reject(error);
              }
            }, 5);
          }),
        path.join(dataDir, "projects.json"),
      )
      .catch((error) => {
        if (!/closed|destroyed/i.test(error.message)) throw error;
      });
    await crashExit;
    application = null;
    assert.equal((await saved())[0].desiredRunning, true);
    client = await launch();
    const restored = await until(
      client.readProject,
      (project) =>
        project?.desiredRunning && project.error?.count > countBeforeRestart,
      "running intent restoration",
      60000,
    );
    assert.match(
      restored.error.message,
      /bad option|unknown option|invalid option/i,
    );
    report.failuresAfterRestart = restored.error.count;
    await client.invoke("project.pause", { id: projectId });
    const paused = await until(
      client.readProject,
      (project) => project.status === "paused" && !project.desiredRunning,
      "pause completion",
    );
    assert.equal((await saved())[0].desiredRunning, false);
    report.pausedErrorCount = paused.error?.count;
    await exitApplication(application);
    application = null;
    client = await launch();
    const restartedPaused = await client.readProject();
    assert.equal(restartedPaused.desiredRunning, false);
    assert.equal(restartedPaused.status, "paused");
    await delay(1800);
    const stillPaused = await client.readProject();
    assert.equal(stillPaused.status, "paused");
    assert.equal(stillPaused.desiredRunning, false);
    assert.deepEqual(stillPaused.error, restartedPaused.error);
    assert.equal((await saved())[0].owner, null);
    assert.deepEqual(uiErrors, []);
    Object.assign(report, {
      windowClosePreservedRunner: true,
      runningIntentRestored: true,
      pausedIntentRestored: true,
      uiErrors,
    });
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await exitApplication(application);
    // Only inspect records created under this test's unique temporary data dir.
    // terminateOwned rechecks the stored worker path and ownership token before killing.
    let projects = [];
    try {
      projects = await saved();
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    for (const project of projects) {
      assert.equal(project.root, projectRoot);
      if (project.owner) await terminateOwned(project.owner);
    }
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
