// Internal stdin/stdout SSH bridge, launched only with the runner's local IPC environment.
const net = require("node:net");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
function requestResource(request, env = process.env) {
  return new Promise((resolve, reject) => {
    if (!env.NEVER_STOP_RESOURCE_PIPE || !env.NEVER_STOP_RESOURCE_TOKEN) {
      reject(new Error("缺少本项目资源入口授权环境"));
      return;
    }
    const socket = net.connect(env.NEVER_STOP_RESOURCE_PIPE);
    let body = "";
    socket.on("connect", () =>
      socket.write(
        JSON.stringify({ ...request, token: env.NEVER_STOP_RESOURCE_TOKEN }) +
          "\n",
      ),
    );
    socket.on("error", reject);
    socket.on("data", (chunk) => {
      body += chunk.toString();
      if (body.length > 3 * 1024 * 1024)
        socket.destroy(new Error("资源响应过大"));
    });
    socket.on("end", () => {
      try {
        const result = JSON.parse(body);
        if (!result.ok) throw new Error(result.error);
        resolve(result);
      } catch (e) {
        reject(e);
      }
    });
  });
}
async function executeSSH(
  resource,
  command,
  { signalSocket, home = os.homedir() } = {},
) {
  const { Client } = require("ssh2");
  const lookup =
    resource.port === 22
      ? resource.host
      : `[${resource.host}]:${resource.port}`;
  let known;
  try {
    ({ stdout: known } = await promisify(execFile)(
      "ssh-keygen",
      ["-F", lookup, "-f", path.join(home, ".ssh", "known_hosts")],
      { windowsHide: true, maxBuffer: 1024 * 1024 },
    ));
  } catch {
    throw new Error(
      "主机尚未在 ~/.ssh/known_hosts 信任，或 ssh-keygen 不可用。请先用现有 SSH 工具确认主机密钥。",
    );
  }
  const keys = known
    .split(/\r?\n/)
    .filter((x) => x && !x.startsWith("#") && !x.startsWith("@"))
    .map((x) => x.trim().split(/\s+/)[2])
    .filter(Boolean);
  const config = {
    host: resource.host,
    port: resource.port,
    username: resource.username || os.userInfo().username,
    readyTimeout: 20000,
    hostVerifier: (key) => keys.includes(key.toString("base64")),
  };
  if (resource.password) config.password = resource.password;
  if (resource.keyPath) config.privateKey = await fs.readFile(resource.keyPath);
  if (resource.passphrase) config.passphrase = resource.passphrase;
  if (!config.privateKey && !config.password) {
    const fallback = path.join(home, ".ssh", "id_ed25519");
    try {
      config.privateKey = await fs.readFile(fallback);
    } catch {
      if (process.env.SSH_AUTH_SOCK) config.agent = process.env.SSH_AUTH_SOCK;
    }
  }
  return new Promise((resolve, reject) => {
    const client = new Client();
    let stdout = "",
      stderr = "";
    let finished = false;
    const finish = (error, result) => {
      if (finished) return;
      finished = true;
      signalSocket?.off("close", disconnected);
      client.end();
      error ? reject(error) : resolve(result);
    };
    const disconnected = () => finish(new Error("资源入口已关闭"));
    signalSocket?.once("close", disconnected);
    const append = (which, chunk) => {
      if (which === "out") stdout += chunk.toString();
      else stderr += chunk.toString();
      if (stdout.length + stderr.length > 1024 * 1024)
        finish(new Error("SSH 输出超过 1 MB，请将详细结果写入文件"));
    };
    client.on("error", (e) => finish(e));
    client.on("ready", () =>
      client.exec(command, (error, stream) => {
        if (error) return finish(error);
        stream.on("data", (d) => append("out", d));
        stream.stderr.on("data", (d) => append("err", d));
        stream.on("error", (e) => finish(e));
        stream.on("close", (code, signal) =>
          finish(null, { stdout, stderr, code: code ?? (signal ? 1 : 0) }),
        );
      }),
    );
    client.connect(config);
  });
}
if (require.main === module) {
  let input = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    input += chunk;
    if (input.length > 65536) {
      process.stderr.write("输入超过上限\n");
      process.exit(1);
    }
  });
  process.stdin.on("end", async () => {
    try {
      const result = await requestResource(JSON.parse(input));
      process.stdout.write(result.stdout || "");
      process.stderr.write(result.stderr || "");
      process.exitCode = result.code || 0;
    } catch (e) {
      process.stderr.write(e.message + "\n");
      process.exitCode = 1;
    }
  });
}
module.exports = { requestResource, executeSSH };
