const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const path = require("node:path");
const execFileAsync = promisify(execFile);

// Electron filters launchItems by executable path. Read the stable value name
// directly so an older portable executable's OS approval is also respected.
async function readWindowsRegistration(name) {
  const encodedName = Buffer.from(name, "utf8").toString("base64");
  const script = `
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$name = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedName}'))
$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run')
$run = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\\Microsoft\\Windows\\CurrentVersion\\Run')
try {
  $approved = $true
  if ($null -ne $key) {
    $value = $key.GetValue($name, $null)
    if ($null -ne $value) {
      if ($value -isnot [byte[]] -or $value.Length -lt 1) { throw 'Invalid startup approval registry value' }
      $approved = $value[0] -eq 0 -or $value[0] -eq 2
    }
  }
  $command = $null
  if ($null -ne $run) { $command = $run.GetValue($name, $null) }
  @{command=$command; approved=$approved} | ConvertTo-Json -Compress
} finally {
  if ($null -ne $key) { $key.Dispose() }
  if ($null -ne $run) { $run.Dispose() }
}
`;
  const executable = path.win32.join(
    process.env.SystemRoot || "C:\\Windows",
    "System32",
    "WindowsPowerShell",
    "v1.0",
    "powershell.exe",
  );
  const { stdout } = await execFileAsync(
    executable,
    [
      "-NoProfile",
      "-NonInteractive",
      "-EncodedCommand",
      Buffer.from(script, "utf16le").toString("base64"),
    ],
    { windowsHide: true, timeout: 10000, maxBuffer: 16384 },
  );
  const state = JSON.parse(stdout.trim());
  if (
    (state.command !== null && typeof state.command !== "string") ||
    typeof state.approved !== "boolean"
  ) {
    throw new Error("无法读取 Windows 自启登记状态");
  }
  return state;
}

async function readWindowsApproval(name) {
  return (await readWindowsRegistration(name)).approved;
}

// Decode Windows command-line quoting without executing the registered command.
function commandArguments(command) {
  const result = [];
  let argument = "",
    quoted = false,
    started = false;
  for (let i = 0; i < command.length; i++) {
    const char = command[i];
    if (!quoted && /\s/.test(char)) {
      if (started) result.push(argument);
      argument = "";
      started = false;
      continue;
    }
    started = true;
    if (char === "\\") {
      let count = 1;
      while (command[i + 1] === "\\") {
        count++;
        i++;
      }
      if (command[i + 1] === '"') {
        argument += "\\".repeat(Math.floor(count / 2));
        i++;
        if (count % 2) argument += '"';
        else quoted = !quoted;
      } else argument += "\\".repeat(count);
    } else if (char === '"') quoted = !quoted;
    else argument += char;
  }
  if (quoted) return [];
  if (started) result.push(argument);
  return result;
}

function createLoginStartup({
  app,
  platform = process.platform,
  env = process.env,
  execPath = process.execPath,
  entryFile,
  name = "com.vantage.never-stop",
  enabled = true,
  readWindowsApproval: readApproval,
  readWindowsRegistration: readRegistration = readWindowsRegistration,
}) {
  const isolated = !enabled || Boolean(env.NEVER_STOP_DATA_DIR);

  async function apply(settings) {
    if (isolated) return { applied: false, reason: "isolated" };
    const openAtLogin = settings.launchAtLogin === true;
    if (platform === "linux") {
      if (openAtLogin) throw new Error("此 Demo 的 Linux 登录自启尚未实现");
      return { applied: false, reason: "unsupported" };
    }
    if (platform !== "win32" && platform !== "darwin") {
      throw new Error("当前平台不支持登录自启");
    }
    const options = { openAtLogin };
    if (platform === "win32") {
      options.name = name;
      options.path = env.PORTABLE_EXECUTABLE_FILE || execPath;
      if (!app.isPackaged && !entryFile)
        throw new Error("开发模式自启缺少应用入口");
      options.args = app.isPackaged
        ? ["--background"]
        : [entryFile, "--background"];
      if (openAtLogin)
        options.enabled =
          (readApproval
            ? await readApproval(name)
            : (await readRegistration(name)).approved) !== false;
    }
    app.setLoginItemSettings(options);
    if (platform === "win32") {
      const item = await readRegistration(name);
      const actual =
        typeof item.command === "string" ? commandArguments(item.command) : [];
      const expected = [options.path, ...options.args];
      const verified = openAtLogin
        ? item.approved === options.enabled &&
          actual.length === expected.length &&
          actual.every((arg, index) => arg === expected[index])
        : item.command === null;
      if (!verified) {
        throw new Error("Windows 自启设置未能验证，请检查系统启动项权限后重试");
      }
    }
    return { applied: true };
  }

  async function reconcile(settings) {
    if (isolated) return { applied: false, reason: "isolated" };
    if (!app.isPackaged) return { applied: false, reason: "development" };
    if (settings.launchAtLogin !== true)
      return { applied: false, reason: "disabled" };
    return apply(settings);
  }

  return { apply, reconcile };
}

module.exports = {
  createLoginStartup,
  readWindowsApproval,
  readWindowsRegistration,
};
