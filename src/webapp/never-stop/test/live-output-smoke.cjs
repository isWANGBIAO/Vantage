// Windows-only explicit UI integration. A temporary C# executable emits known
// Claude stream-json fixtures; this test never calls an installed Agent/model.
const { _electron: electron } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright",
);
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { terminateOwned } = require("../core/process-owner.cjs");
const exec = promisify(execFile);
const delay = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const csharpString = (value) => '@"' + value.replaceAll('"', '""') + '"';

async function main() {
  assert.equal(
    process.platform,
    "win32",
    "This fixture requires the Windows .NET Framework compiler",
  );
  const compiler = path.join(
    process.env.WINDIR || process.env.SystemRoot,
    "Microsoft.NET",
    "Framework64",
    "v4.0.30319",
    "csc.exe",
  );
  await fs.access(compiler);
  const temporary = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-live-ui-"),
  );
  const bin = path.join(temporary, "bin");
  const projectRoot = path.join(temporary, "Live output fixture");
  const secondRoot = path.join(temporary, "Other fixture");
  const movedRoot = path.join(temporary, "Moved fixture");
  const dataDir = path.join(temporary, "data");
  await Promise.all([
    fs.mkdir(bin),
    fs.mkdir(projectRoot),
    fs.mkdir(secondRoot),
    fs.mkdir(movedRoot),
  ]);
  const events = [
    { type: "system", subtype: "init", session_id: "never-stop-live-fixture" },
    { type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'thinking_delta', thinking: 'PRIVATE_THINKING_FIXTURE' } } },
    { type: 'stream_event', event: { type: 'content_block_delta', index: 1, delta: { type: 'text_delta', text: 'PRIVATE_PARTIAL_FIXTURE' } } },
    {
      type: "assistant",
      message: {
        content: [
          {
            type: "text",
            text: "正在检查临时样例目录。实时输出在调用结束前可见。<script>fixture</script>",
          },
          {
            type: "tool_use",
            id: "fixture-tool",
            name: "ReadFixture",
            input: { path: "sample.txt" },
          },
        ],
      },
    },
    {
      type: "user",
      message: {
        content: [
          {
            type: "tool_result",
            tool_use_id: "fixture-tool",
            content: "样例工具返回结果：读取完成。",
          },
        ],
      },
    },
  ];
  const source = `using System; using System.IO; using System.Text; using System.Threading;
class Fixture { static void Main(string[] args) {
Console.OutputEncoding = new UTF8Encoding(false);
Console.InputEncoding = new UTF8Encoding(false);
Console.In.ReadToEnd();
File.WriteAllText("fixture-cwd.txt", Environment.CurrentDirectory);
${events.map((event) => `Console.WriteLine(${csharpString(JSON.stringify(event))});`).join("\n")}
Console.Error.WriteLine(${csharpString('[claude-code:unrecognized_model] {"model":"custom-model","query_source":"compact"}')});
Console.Error.WriteLine("API Error: 400 synthetic fixture failure");
Console.Error.Flush();
Console.Out.Flush();
Thread.Sleep(120000);
} }`;
  const sourcePath = path.join(temporary, "Fixture.cs");
  const fakeCli = path.join(bin, "claude.exe");
  await fs.writeFile(sourcePath, source, "utf8");
  await exec(
    compiler,
    ["/nologo", "/target:exe", `/out:${fakeCli}`, sourcePath],
    { windowsHide: true },
  );
  const env = { ...process.env, NEVER_STOP_DATA_DIR: dataDir };
  for (const key of Object.keys(env))
    if (key.toLowerCase() === "path") delete env[key];
  env.PATH = `${bin}${path.delimiter}${process.env.PATH || process.env.Path || ""}`;
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;
  let application;
  let project;
  const errors = [];
  try {
    application = await electron.launch({
      executablePath: process.env.NEVER_STOP_ELECTRON || require("electron"),
      args: [path.resolve(__dirname, "../main.cjs")],
      env,
      timeout: 30000,
    });
    const page = await application.firstWindow();
    if (process.env.NEVER_STOP_ELECTRON) {
      const packaged = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, path: app.getAppPath(), version: app.getVersion() }));
      assert.equal(packaged.packaged, true);
      assert.match(packaged.path, /app\.asar$/);
      assert.equal(packaged.version, require('../electron-builder.cjs').extraMetadata.version);
    }
    page.on("pageerror", (error) => errors.push(error.message));
    await page.waitForFunction(
      () => typeof window.neverStop?.invoke === "function",
    );
    if (process.env.NEVER_STOP_ELECTRON) await page.getByText(`独立 Demo · v${require('../electron-builder.cjs').extraMetadata.version}`, { exact: true }).waitFor();
    const invoke = (method, payload) =>
      page.evaluate(
        ({ method, payload }) => window.neverStop.invoke(method, payload),
        { method, payload },
      );
    project = await invoke("project.add", {
      root: projectRoot,
      backend: "claude",
    });
    const goal = await invoke("goal.read", { id: project.id });
    const text =
      "# Live output fixture\nOnly the local fake process emits fixture events.";
    await invoke("goal.save", { id: project.id, text, version: goal.version });
    await invoke("goal.publish", { id: project.id, text });
    await invoke("project.start", { id: project.id });
    const log = page.getByTestId("live-output");
    await log
      .getByText(
        "正在检查临时样例目录。实时输出在调用结束前可见。<script>fixture</script>",
        { exact: true },
      )
      .waitFor({ timeout: 30000 });
    await log
      .getByText("样例工具返回结果：读取完成。", { exact: true })
      .waitFor();
    assert.ok((await log.innerText()).includes('模型正在思考'));
    assert.ok((await log.innerText()).includes('正在生成回复'));
    assert.ok(!(await log.innerText()).includes('PRIVATE_'));
    assert.ok((await log.innerText()).includes("ReadFixture"));
    const modelNotice = log.locator('.live-entry').filter({ hasText: '模型兼容性提示：custom-model' });
    await modelNotice.waitFor();
    assert.match(await modelNotice.getAttribute('class'), /live-kind-status/);
    assert.equal(await modelNotice.getByText('错误', { exact: true }).count(), 0);
    const apiFailure = log.locator('.live-entry').filter({ hasText: 'API Error: 400 synthetic fixture failure' });
    await apiFailure.waitFor();
    assert.match(await apiFailure.getAttribute('class'), /live-kind-error/);
    assert.equal(await apiFailure.getByText('错误', { exact: true }).count(), 1);
    assert.equal(await log.locator("script").count(), 0);
    const running = (await invoke("state")).projects.find(
      (item) => item.id === project.id,
    );
    assert.equal(running.status, "running");
    assert.equal(running.desiredRunning, true);
    assert.equal(running.sessionId, "never-stop-live-fixture");
    const runtime = page.getByTestId('project-runtime');
    const firstRuntime = await runtime.innerText();
    await delay(2100);
    assert.notEqual(await runtime.innerText(), firstRuntime, 'running time advances live');
    assert.equal(
      await fs.readFile(path.join(projectRoot, "fixture-cwd.txt"), "utf8"),
      projectRoot,
    );
    await log.focus();
    await log.press("Space");
    assert.equal(
      (await invoke("state")).projects.find((item) => item.id === project.id)
        .desiredRunning,
      true,
    );
    await page.getByRole("button", { name: "暂停跟随", exact: true }).click();
    await page.getByRole("button", { name: "跟随最新", exact: true }).waitFor();
    await page
      .getByRole("button", { name: "复制实时输出", exact: true })
      .click();
    await page.getByText("已复制当前显示的输出", { exact: true }).waitFor();
    const copied = await application.evaluate(({ clipboard }) =>
      clipboard.readText(),
    );
    assert.ok(copied.includes("ReadFixture"));
    assert.ok(copied.includes("样例工具返回结果"));
    const screenshot = path.join(temporary, "live-output.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await page.getByRole("button", { name: "实时运行", exact: true }).click();
    assert.equal(await log.count(), 0);
    await delay(1100);
    assert.equal(
      (await invoke("state")).projects.find((item) => item.id === project.id)
        .desiredRunning,
      true,
    );
    await page.getByRole("button", { name: "实时运行", exact: true }).click();
    await log
      .getByText("样例工具返回结果：读取完成。", { exact: true })
      .waitFor();
    const second = await invoke("project.add", {
      root: secondRoot,
      backend: "claude",
    });
    await page
      .locator(".project-item")
      .filter({ hasText: "Other fixture" })
      .click();
    await log.getByText("等待本次运行输出", { exact: true }).waitFor();
    assert.ok((await runtime.innerText()).includes('00:00:00'), 'new project starts at zero');
    assert.equal((await log.innerText()).includes("ReadFixture"), false);
    await page
      .locator(".project-item")
      .filter({ hasText: "Live output fixture" })
      .click();
    await log
      .getByText("样例工具返回结果：读取完成。", { exact: true })
      .waitFor();
    await invoke("project.pause", { id: project.id });
    await delay(650);
    assert.equal(
      (await invoke("state")).projects.find((item) => item.id === project.id)
        .desiredRunning,
      false,
    );
    assert.ok((await log.innerText()).includes("样例工具返回结果"));
    const pausedRuntime = await runtime.innerText();
    await delay(2100);
    assert.equal(await runtime.innerText(), pausedRuntime, 'paused time is frozen');
    await page
      .getByRole("button", { name: "清空实时输出", exact: true })
      .click();
    await log.getByText("等待本次运行输出", { exact: true }).waitFor();
    await delay(650);
    assert.equal(
      (await invoke("output.read", { id: project.id, after: 0 })).entries
        .length,
      0,
    );
    assert.equal(
      (await invoke("state")).projects.find((item) => item.id === project.id)
        .desiredRunning,
      false,
    );
    const beforeMove = (await invoke('state')).projects.find(item => item.id === project.id);
    await fs.writeFile(path.join(movedRoot, 'goal.md'), 'different target goal');
    await page.getByRole('button', { name: '更改目录', exact: true }).click();
    await page.getByLabel('新项目目录', { exact: true }).fill(movedRoot);
    await page.getByRole('button', { name: '确认更改', exact: true }).click();
    await page.waitForFunction(() => document.body.innerText.includes('目录切换冲突'));
    assert.equal((await invoke('state')).projects.find(item => item.id === project.id).root, projectRoot);
    assert.equal(await fs.readFile(path.join(movedRoot, 'goal.md'), 'utf8'), 'different target goal');
    await fs.unlink(path.join(movedRoot, 'goal.md'));
    const largeProgress = Buffer.alloc(7152810, 'x');
    await fs.writeFile(path.join(movedRoot, 'progress.md'), largeProgress);
    await fs.mkdir(path.join(movedRoot, '.never-stop'));
    await fs.writeFile(path.join(movedRoot, '.never-stop', 'progress.json'), JSON.stringify({
      schema_version: 1, updated_at: '2026-09-14T12:00:00+08:00', overall_percent: 12,
      summary_markdown: 'Large Markdown fixture still displays structured progress',
      radar: { axes: [] }, suggestions_markdown: '',
    }));
    await page.getByRole('button', { name: '确认更改', exact: true }).click();
    await page.waitForFunction(root => document.querySelector('.root-path')?.textContent === root, movedRoot);
    const afterMove = (await invoke('state')).projects.find(item => item.id === project.id);
    assert.equal(afterMove.root, movedRoot);
    assert.equal(afterMove.totalRunMs, beforeMove.totalRunMs);
    assert.equal(afterMove.desiredRunning, false);
    assert.equal(afterMove.sessionId, null);
    const migratedProgress = await invoke('progress.read', { id: project.id });
    assert.equal(migratedProgress.snapshot.overall_percent, 12);
    assert.ok((await fs.readFile(path.join(movedRoot, 'progress.md'))).equals(largeProgress));
    assert.equal(await fs.readFile(path.join(movedRoot, 'goal.md'), 'utf8'), text);
    assert.equal(await fs.readFile(path.join(projectRoot, 'goal.md'), 'utf8'), text);
    await invoke('project.start', { id: project.id });
    for (let attempt = 0; attempt < 80; attempt++) {
      try { if (await fs.readFile(path.join(movedRoot, 'fixture-cwd.txt'), 'utf8') === movedRoot) break; } catch { /* Wait for the owned fixture. */ }
      await delay(100);
    }
    assert.equal(await fs.readFile(path.join(movedRoot, 'fixture-cwd.txt'), 'utf8'), movedRoot);
    await invoke('project.pause', { id: project.id });
    await page.screenshot({ path: path.join(temporary, 'directory-changed.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify(
        {
          temporary,
          screenshot,
          liveOutputBeforeExit: true,
          partialActivityVisibleWithoutRawReasoning: true,
          modelCatalogWarningIsStatusAndApiFailureIsError: true,
          assistantToolResultVisible: true,
          plainTextEscaped: true,
          spaceDidNotPause: true,
          clipboardCopied: true,
          collapsePreservedRunning: true,
          projectIsolation: true,
          pauseRetainedOutput: true,
          clearOnlyDisplay: true,
          runtimeAdvancesAndFreezes: true,
          directoryChangedWithTimeAndGoalPreserved: true,
          conflictingTargetPreserved: true,
          largeProgressMigratedAndPreserved: true,
          newDirectoryExecuted: true,
          uiErrors: errors,
          secondProjectId: second.id,
        },
        null,
        2,
      ),
    );
  } finally {
    if (application && application.process().exitCode === null) {
      const exited = new Promise((resolve) =>
        application.process().once("exit", resolve),
      );
      await application.evaluate(({ app }) => app.exit(0));
      await exited;
    }
    let records = [];
    try {
      records = JSON.parse(
        await fs.readFile(path.join(dataDir, "projects.json"), "utf8"),
      );
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    for (const record of records) {
      assert.ok([projectRoot, secondRoot, movedRoot].includes(record.root));
      if (record.owner) await terminateOwned(record.owner);
    }
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
