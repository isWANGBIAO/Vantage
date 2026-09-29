// Explicit Windows native integration. Only a UUID-named test login item is changed.
// Electron APIs and registry writes are real; only app.isPackaged is represented
// by a facade so the dev Electron executable can exercise portable reconciliation.
const { _electron: electron } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright",
);
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const assert = require("node:assert/strict");
const { randomUUID } = require("node:crypto");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const exec = promisify(execFile);
const productionName = "com.vantage.never-stop";
const registryPaths = {
  run: "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
  approval:
    "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run",
};
async function registry(action, name) {
  if (action !== "read" && !/^never-stop-test-[0-9a-f-]{36}$/.test(name))
    throw Error("Refusing to alter a non-test registry value");
  const script = `
$ErrorActionPreference = 'Stop'
$name = $env:NEVER_STOP_SMOKE_KEY
$paths = @{ run = '${registryPaths.run}'; approval = '${registryPaths.approval}' }
$result = @{}
foreach ($label in @('run','approval')) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($paths[$label], $${action !== "read" ? "true" : "false"})
  try {
    if ('${action}' -eq 'cleanup') { if ($null -ne $key) { $key.DeleteValue($name, $false) }; continue }
    if ('${action}' -eq 'disable' -and $label -eq 'approval') {
      if ($null -eq $key) { $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($paths[$label]) }
      [byte[]]$bytes = @(3,0,0,0,0,0,0,0,0,0,0,0)
      $key.SetValue($name, $bytes, [Microsoft.Win32.RegistryValueKind]::Binary)
    }
    if ($null -eq $key -or $key.GetValueNames() -notcontains $name) { $result[$label] = $null; continue }
    $value = $key.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $result[$label] = @{ kind = $key.GetValueKind($name).ToString(); value = $(if ($value -is [byte[]]) { [Convert]::ToBase64String($value) } else { [string]$value }) }
  } finally { if ($null -ne $key) { $key.Dispose() } }
}
$result | ConvertTo-Json -Compress -Depth 4
`;
  const shell = path.join(
    process.env.SystemRoot || "C:\\Windows",
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
  );
  const { stdout } = await exec(
    shell,
    [
      "-NoProfile",
      "-NonInteractive",
      "-EncodedCommand",
      Buffer.from(script, "utf16le").toString("base64"),
    ],
    {
      windowsHide: true,
      timeout: 15000,
      maxBuffer: 16384,
      env: { ...process.env, NEVER_STOP_SMOKE_KEY: name },
    },
  );
  return JSON.parse(stdout.trim());
}
async function main() {
  if (process.platform !== "win32")
    throw Error("This smoke test requires Windows native registry APIs");
  const name = "never-stop-test-" + randomUUID();
  const beforeProduction = await registry("read", productionName);
  assert.deepEqual(await registry("read", name), { run: null, approval: null });
  const temporary = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-startup-"),
  );
  const entryFile = path.join(temporary, "main.cjs");
  const helperFile = path.resolve(__dirname, "../core/login-startup.cjs");
  const oldPath = path.join(temporary, "old location", "Never Stop.exe");
  const newPath = path.join(temporary, "new location", "Never Stop.exe");
  const thirdPath = path.join(temporary, "latest location", "Never Stop.exe");
  for (const file of [oldPath, newPath, thirdPath]) {
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, Buffer.alloc(0));
  }
  await fs.writeFile(
    entryFile,
    `const {app,BrowserWindow}=require('electron');app.setPath('userData',${JSON.stringify(path.join(temporary, "data"))});globalThis.startupSmoke={create:require(${JSON.stringify(helperFile)}).createLoginStartup};app.whenReady().then(()=>{const w=new BrowserWindow({show:false});w.loadURL('about:blank');});`,
  );
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  let application;
  const report = {
    platform: process.platform,
    portablePathReconciled: false,
    backgroundArgument: false,
    osDisabledPreserved: false,
    falseRemovesRunValue: false,
    isolatedEnvironmentNoOp: false,
    productionValuesUnchanged: false,
    testValuesCleaned: false,
  };
  try {
    application = await electron.launch({
      executablePath: require("electron"),
      args: [entryFile],
      env,
      timeout: 30000,
    });
    await application.evaluate(
      ({ app }, { name, oldPath }) =>
        app.setLoginItemSettings({
          name,
          path: oldPath,
          args: ["--background"],
          openAtLogin: true,
        }),
      { name, oldPath },
    );
    assert.ok((await registry("read", name)).run.value.includes(oldPath));
    const invoke = (method, portablePath, launchAtLogin, isolated = false) =>
      application.evaluate(
        async ({ app }, args) => {
          const facade = {
            isPackaged: true,
            setLoginItemSettings: (options) =>
              app.setLoginItemSettings(options),
            getLoginItemSettings: (options) => {
              const result = app.getLoginItemSettings(options);
              globalThis.startupNativeRead = {
                options,
                result,
                named: app.getLoginItemSettings({
                  ...options,
                  name: args.name,
                }),
              };
              return result;
            },
          };
          const helper = globalThis.startupSmoke.create({
            app: facade,
            platform: "win32",
            env: {
              PORTABLE_EXECUTABLE_FILE: args.portablePath,
              ...(args.isolated ? { NEVER_STOP_DATA_DIR: args.dataDir } : {}),
            },
            execPath: process.execPath,
            entryFile: args.entryFile,
            name: args.name,
          });
          return helper[args.method]({ launchAtLogin: args.launchAtLogin });
        },
        {
          method,
          portablePath,
          launchAtLogin,
          isolated,
          name,
          entryFile,
          dataDir: path.join(temporary, "isolated"),
        },
      );
    assert.equal((await invoke("reconcile", newPath, true)).applied, true);
    let values = await registry("read", name);
    assert.ok(values.run.value.includes(newPath));
    assert.ok(!values.run.value.includes(oldPath));
    assert.match(values.run.value, /--background/);
    report.portablePathReconciled = true;
    report.backgroundArgument = true;
    await registry("disable", name);
    assert.equal((await invoke("reconcile", thirdPath, true)).applied, true);
    values = await registry("read", name);
    assert.ok(values.run.value.includes(thirdPath));
    const approval = Buffer.from(values.approval.value, "base64");
    assert.notEqual(approval[0], 0);
    assert.notEqual(approval[0], 2);
    report.osDisabledPreserved = true;
    const beforeIsolation = await registry("read", name);
    assert.deepEqual(await invoke("reconcile", oldPath, true, true), {
      applied: false,
      reason: "isolated",
    });
    assert.deepEqual(await invoke("apply", oldPath, false, true), {
      applied: false,
      reason: "isolated",
    });
    assert.deepEqual(await registry("read", name), beforeIsolation);
    report.isolatedEnvironmentNoOp = true;
    assert.equal((await invoke("apply", thirdPath, false)).applied, true);
    assert.equal((await registry("read", name)).run, null);
    report.falseRemovesRunValue = true;
  } catch (error) {
    if (application)
      console.error(
        "native-login-read",
        await application.evaluate(() => globalThis.startupNativeRead),
      );
    console.error("native-test-registry", await registry("read", name));
    throw error;
  } finally {
    try {
      if (application) await application.close();
    } finally {
      await registry("cleanup", name);
      assert.deepEqual(await registry("read", name), {
        run: null,
        approval: null,
      });
      report.testValuesCleaned = true;
      assert.deepEqual(
        await registry("read", productionName),
        beforeProduction,
        "Production Run/StartupApproved values must remain byte-for-byte unchanged",
      );
      report.productionValuesUnchanged = true;
      await fs.writeFile(
        path.join(temporary, "result.json"),
        JSON.stringify(report, null, 2),
      );
    }
  }
  console.log(
    JSON.stringify(
      { ...report, artifact: path.join(temporary, "result.json") },
      null,
      2,
    ),
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
