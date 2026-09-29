"use strict";
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { promisify } = require("node:util");
const exec = promisify(execFile);
const liveChildren = new Map();
async function ownsProcess(record) {
  if (!record?.pid || !record.token) return false;
  const workerPath = record.workerPath || __filename;
  if (
    !path.isAbsolute(workerPath) ||
    path.basename(workerPath) !== "process-owner.cjs"
  )
    return false;
  try {
    let cmd;
    if (process.platform === "win32") {
      const r = await exec(
        "powershell.exe",
        [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          `(Get-CimInstance Win32_Process -Filter "ProcessId = ${Number(record.pid)}").CommandLine`,
        ],
        { windowsHide: true, maxBuffer: 65536 },
      );
      cmd = r.stdout;
    } else if (process.platform === "darwin") {
      cmd = (
        await exec("ps", ["-p", String(record.pid), "-o", "command="], {
          maxBuffer: 65536,
        })
      ).stdout;
    } else cmd = await fs.readFile(`/proc/${record.pid}/cmdline`, "utf8");
    if (!cmd.trim()) {
      try {
        process.kill(record.pid, 0);
      } catch (e) {
        if (e.code === "ESRCH") return false;
        throw e;
      }
      throw Error("Cannot read command line of a live process candidate");
    }
    return cmd.includes(workerPath) && cmd.includes(record.token);
  } catch (e) {
    if (process.platform !== "win32" && e.code === "ENOENT") return false;
    if (process.platform === "darwin") {
      try {
        process.kill(record.pid, 0);
      } catch (probe) {
        if (probe.code === "ESRCH") return false;
      }
    }
    throw Error("Cannot verify process ownership: " + e.message);
  }
}
async function terminateOwned(record, { trusted = false } = {}) {
  if (!record?.pid) return;
  const live = liveChildren.get(record.pid);
  const verifiedHandle =
    trusted && live && live.token === record.token && !live.exited;
  if (!verifiedHandle && !(await ownsProcess(record))) return;
  if (process.platform === "win32") {
    try {
      await exec("taskkill.exe", ["/PID", String(record.pid), "/T", "/F"], {
        windowsHide: true,
        maxBuffer: 65536,
      });
    } catch (e) {
      try {
        process.kill(record.pid, 0);
      } catch {
        return;
      }
      throw Error("Unable to stop owned process tree");
    }
  } else {
    try {
      process.kill(-record.pid, "SIGINT");
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
    try {
      process.kill(-record.pid, "SIGKILL");
    } catch (e) {
      if (e.code !== "ESRCH") throw e;
    }
  }
}
function launchOwned(spec, root, prompt, token, onEvent) {
  const child = spawn(process.execPath, [__filename, "--worker", token], {
    cwd: root,
    windowsHide: true,
    detached: process.platform !== "win32",
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  });
  const ownership = { token, exited: false };
  if (child.pid) liveChildren.set(child.pid, ownership);
  child.once("exit", () => {
    ownership.exited = true;
    liveChildren.delete(child.pid);
  });
  const { createLineReader } = require("./adapters.cjs");
  let resolve;
  const done = new Promise((r) => (resolve = r));
  let settled = false;
  const finish = (result) => {
    if (!settled) {
      settled = true;
      resolve(result);
    }
  };
  child.stdout.on(
    "data",
    createLineReader((line) => {
      try {
        const e = JSON.parse(line);
        if (e.type === "done") finish(e);
        else onEvent(e);
      } catch {}
    }),
  );
  child.stderr.resume();
  child.on("error", (e) => finish({ code: 1, error: e.message }));
  child.on("exit", (code, signal) => finish({ code: code ?? 1, signal }));
  child.stdin.on("error", () => {});
  return {
    child,
    record: { pid: child.pid, token, workerPath: __filename },
    done,
    sent: false,
    send() {
      this.sent = true;
      child.stdin.end(JSON.stringify({ spec, prompt }));
    },
  };
}
async function worker() {
  const { createLineReader, parseEvent } = require("./adapters.cjs");
  const { createDisplayParser, sanitizeOutput, createStderrReader } = require("./live-output.cjs");
  let input = "";
  for await (const c of process.stdin) {
    input += c;
    if (input.length > 4 * 1024 * 1024) throw Error("Input too large");
  }
  const { spec, prompt } = JSON.parse(input);
  const send = (e) => process.stdout.write(JSON.stringify(e) + "\n");
  let lastError = "",
    stderr = "";
  let sessionSent = false;
  const cliEnv = { ...process.env, ...(spec.env || {}) };
  delete cliEnv.ELECTRON_RUN_AS_NODE;
  const secrets = Object.entries(cliEnv)
    .filter(([key, value]) => /token|password|passwd|secret|api.?key|private.?key/i.test(key) && typeof value === 'string' && value.length > 3)
    .map(([, value]) => value);
  secrets.push(...(Array.isArray(spec.redactionSecrets) ? spec.redactionSecrets.filter(value => typeof value === 'string' && value) : []));
  const parseDisplay = createDisplayParser({ secrets });
  let completed = false;
  let pendingOutput = [], pendingBytes = 0, dropped = 0, blocked = false;
  const enqueue = entries => {
    for (const entry of entries) {
      const safe = { kind: entry.kind, text: sanitizeOutput(entry.text, secrets) };
      if (!safe.text) continue;
      const bytes = Buffer.byteLength(JSON.stringify(safe));
      while (pendingOutput.length && (pendingOutput.length >= 31 || pendingBytes + bytes > 24000)) {
        pendingBytes -= pendingOutput.shift().bytes; dropped++;
      }
      pendingOutput.push({ entry: safe, bytes }); pendingBytes += bytes;
    }
  };
  const flushOutput = (force = false) => {
    if ((!force && blocked) || (!pendingOutput.length && !dropped)) return;
    const entries = pendingOutput.map(item => item.entry);
    if (dropped) entries.unshift({ kind: 'status', text: `输出较多，已省略 ${dropped} 条较早内容。` });
    pendingOutput = []; pendingBytes = 0; dropped = 0;
    blocked = !process.stdout.write(JSON.stringify({ type: 'output', entries }) + '\n');
  };
  process.stdout.on('drain', () => { blocked = false; });
  const outputTimer = setInterval(flushOutput, 100); outputTimer.unref();
  const child = spawn(spec.command, spec.args, {
    cwd: process.cwd(),
    windowsHide: true,
    env: cliEnv,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const stdoutLines = createLineReader((line) => {
      const visible = parseDisplay(line);
      enqueue(visible);
      if (spec.backend === 'claude') {
        try {
          const event = JSON.parse(line);
          if (event?.type === 'result') {
            completed = event.subtype === 'success' && event.is_error !== true;
            // The CLI may recover from an API error itself. Its terminal result
            // is authoritative; retain the earlier visible error, not failure.
            if (completed) lastError = '';
          }
        } catch { /* Non-JSON output is not a completion event. */ }
      }
      const e = parseEvent(line);
      if (e) {
        if (e.type === "error") lastError = visible.find(entry => entry.kind === 'error')?.text || 'Agent 执行失败';
        if (e.type === "session" && !sessionSent) {
          sessionSent = true;
          send(e);
        }
      }
    }, 1024 * 1024);
  child.stdout.on('data', stdoutLines);
  const stderrLines = createStderrReader(entries => {
    enqueue(entries);
    const failure = entries.findLast(entry => entry.kind === 'error');
    if (failure) stderr = failure.text;
  }, secrets);
  child.stderr.on("data", (c) => {
    stderrLines(c);
  });
  child.stdin.on("error", () => {});
  child.stdin.end(prompt);
  child.on("error", (e) => {
    lastError = sanitizeOutput(e.message, secrets);
  });
  child.on("close", (code) => {
    stdoutLines.flush();
    stderrLines.flush();
    if (spec.backend === 'claude' && code === 0 && !completed && !lastError) {
      lastError = 'Claude 调用不完整：未收到成功的最终 result 事件；不能把连接结束当作任务完成。';
      enqueue([{ kind: 'error', text: lastError }]);
    }
    clearInterval(outputTimer);
    flushOutput(true);
    send({
      type: "done",
      code: lastError ? (code || 1) : (code ?? 1),
      error: sanitizeOutput(lastError || (code ? stderr : ""), secrets),
    });
    setInterval(() => {}, 60000);
  });
}
if (process.argv[2] === "--worker")
  worker().catch(() => {
    process.stdout.write(
      JSON.stringify({
        type: "done",
        code: 1,
        error: "Runner worker initialization failed",
      }) + "\n",
    );
    process.exitCode = 1;
  });
module.exports = { ownsProcess, terminateOwned, launchOwned };
