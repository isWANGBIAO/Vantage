"use strict";
const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID, createHash } = require("node:crypto");
const net = require("node:net");
const { EventEmitter } = require("node:events");
const { adapterFactory: defaultAdapter, redact } = require("./adapters.cjs");
const { launchOwned, terminateOwned } = require("./process-owner.cjs");
class Runner extends EventEmitter {
  constructor({
    dataDir,
    adapterFactory = defaultAdapter,
    resourcesPrompt = async () => "",
    executionEnv = async () => ({}),
    outputSecrets = async () => [],
    principles = "",
    monotonicNow = () => performance.now(),
    wallNow = () => Date.now(),
    checkpointMs = 15000,
  }) {
    super();
    this.dataDir = dataDir;
    this.adapterFactory = adapterFactory;
    this.terminateProcess = terminateOwned;
    this.resourcesPrompt = resourcesPrompt;
    this.executionEnv = executionEnv;
    this.outputSecrets = outputSecrets;
    this.principles = principles;
    this.monotonicNow = monotonicNow;
    this.wallNow = wallNow;
    this.checkpointMs = checkpointMs;
    this.projects = [];
    this.states = new Map();
    this.saves = Promise.resolve();
    this.closed = false;
    this.locked = false;
    this.directoryQueue = Promise.resolve();
  }
  async init() {
    await fs.mkdir(this.dataDir, { recursive: true });
    this.file = path.join(this.dataDir, "projects.json");
    this.lock = path.join(this.dataDir, "runner.lock");
    if (process.platform === "win32") {
      // Named-pipe ownership lives in the kernel, so a crash releases it without
      // a stale PID file or a creation-before-owner-write recovery window.
      const canonical = (await fs.realpath(this.dataDir)).toLowerCase();
      const key = createHash("sha256").update(canonical).digest("hex");
      const server = net.createServer((socket) => socket.end());
      await new Promise((resolve, reject) => {
        server.once("error", (e) =>
          reject(
            Error(
              e.code === "EADDRINUSE"
                ? "A runner is already active for this data directory"
                : e.message,
            ),
          ),
        );
        server.listen(`\\\\.\\pipe\\vantage-never-stop-${key}`, resolve);
      });
      this.lockServer = server;
    } else {
      try {
        await fs.mkdir(this.lock);
      } catch (e) {
        if (e.code !== "EEXIST") throw e;
        let owner;
        try {
          owner = Number(
            await fs.readFile(path.join(this.lock, "pid"), "utf8"),
          );
        } catch {
          throw Error("Runner lock has no owner; inspect before recovering");
        }
        try {
          process.kill(owner, 0);
          throw Error("A runner is already active for this data directory");
        } catch (e) {
          if (e.code !== "ESRCH") throw e;
        }
        await fs.rm(this.lock, { recursive: true });
        await fs.mkdir(this.lock);
      }
      await fs.writeFile(path.join(this.lock, "pid"), String(process.pid));
    }
    this.locked = true;
    try {
      this.projects = JSON.parse(await fs.readFile(this.file, "utf8"));
    } catch (e) {
      if (e.code !== "ENOENT") throw e;
    }
    for (const p of this.projects) {
      p.totalRunMs =
        Number.isFinite(p.totalRunMs) && p.totalRunMs >= 0 ? p.totalRunMs : 0;
      delete p.runTimerStartedAt;
      this._state(p);
      if (p.owner) {
        await this.terminateProcess(p.owner);
        if (p.owner.pid && !p.sessionId) p.sessionUncertain = true;
        p.owner = null;
      }
      p.status = p.desiredRunning ? "running" : "paused";
      this._syncRunTimer(p);
    }
    await this._save();
    this.runtimeCheckpoint = setInterval(() => {
      if (
        this.closed ||
        this.runtimeCheckpointPending ||
        !this.projects.some((p) => this._state(p).runtimeAnchor !== null)
      )
        return;
      this.runtimeCheckpointPending = true;
      this._save()
        .then(() => this._changed())
        .catch((error) => {
          for (const p of this.projects)
            if (this._state(p).runtimeAnchor !== null) {
              p.error = {
                message: `累计运行时间保存失败：${redact(error.message)}`,
                count: 1,
                at: new Date().toISOString(),
              };
            }
          this._changed();
        })
        .finally(() => {
          this.runtimeCheckpointPending = false;
        });
    }, this.checkpointMs);
    this.runtimeCheckpoint.unref();
    for (const p of this.projects) this._kick(p);
    return this;
  }
  snapshot() {
    const mono = this.monotonicNow(),
      wall = this.wallNow();
    return structuredClone(
      this.projects.map(({ owner, ...p }) => {
        const anchor = this._state(p).runtimeAnchor;
        return {
          ...p,
          totalRunMs: Math.floor(
            p.totalRunMs + (anchor === null ? 0 : Math.max(0, mono - anchor)),
          ),
          runTimerStartedAt: anchor === null ? null : wall,
        };
      }),
    );
  }
  _syncRunTimer(p, now = this.monotonicNow()) {
    const s = this._state(p);
    if (s.runtimeAnchor !== null)
      p.totalRunMs += Math.max(0, now - s.runtimeAnchor);
    s.runtimeAnchor = p.desiredRunning && !this.closed ? now : null;
  }
  _state(p) {
    if (!this.states.has(p.id))
      this.states.set(p.id, {
        generation: 0,
        resetEpoch: 0,
        pending: 0,
        queue: Promise.resolve(),
        loop: null,
        handle: null,
        wake: null,
        reason: "正常续跑",
        runtimeAnchor: null,
      });
    return this.states.get(p.id);
  }
  _project(id) {
    const p = this.projects.find((p) => p.id === id);
    if (!p) throw Error("Project not found");
    if (this._state(p).directoryChanging)
      throw Error("项目目录正在切换，请稍后重试操作");
    return p;
  }
  _enqueueDirectory(operation) {
    const result = this.directoryQueue.then(operation);
    this.directoryQueue = result.catch(() => {});
    return result;
  }
  _save() {
    const now = this.monotonicNow();
    for (const p of this.projects) this._syncRunTimer(p, now);
    const body = JSON.stringify(this.projects, null, 2);
    const operation = this.saves.then(async () => {
      const tmp = this.file + ".tmp";
      await fs.writeFile(tmp, body, { mode: 0o600 });
      await fs.rename(tmp, this.file);
    });
    this.saves = operation.catch(() => {});
    return operation;
  }
  _changed() {
    this.emit("change", this.snapshot());
  }
  addProject(options) {
    return this._enqueueDirectory(() => this._addProject(options));
  }
  async _addProject({ root, backend, name }) {
    if (this.closed) throw Error("Runner is shut down");
    if (!["codex", "claude"].includes(backend))
      throw Error("Unsupported backend");
    const real = await fs.realpath(root);
    if (!(await fs.stat(real)).isDirectory())
      throw Error("Project root must be a directory");
    const key = process.platform === "win32" ? real.toLowerCase() : real;
    if (
      this.projects.some(
        (p) =>
          (process.platform === "win32" ? p.root.toLowerCase() : p.root) ===
          key,
      )
    )
      throw Error("Project directory already exists");
    const p = {
      id: randomUUID(),
      root: real,
      name: name || path.basename(real),
      backend,
      desiredRunning: false,
      status: "paused",
      sessionId: null,
      publishedGoal: "",
      publishedRevision: 0,
      adoptedRevision: 0,
      error: null,
      resourceIds: [],
      owner: null,
      totalRunMs: 0,
    };
    this.projects.push(p);
    this._state(p);
    await this._save();
    this._changed();
    return this.snapshot().find((x) => x.id === p.id);
  }
  async changeDirectory(id, root, prepare = async () => {}) {
    if (this.closed) throw Error("Runner is shut down");
    const p = this._project(id),
      s = this._state(p);
    const wasRunning = p.desiredRunning,
      oldRoot = p.root;
    s.directoryChanging = true;
    return this._enqueueDirectory(async () => {
      let oldSession;
      try {
        const selected = await fs.realpath(root).catch(() => null);
        const key = (value) =>
          process.platform === "win32" ? value.toLowerCase() : value;
        if (selected && key(selected) === key(oldRoot))
          return this.snapshot().find((project) => project.id === id);
        await this._control(
          p,
          () => {
            p.desiredRunning = false;
            p.status = "paused";
          },
          async () => {
            if (!this.projects.includes(p))
              throw Error("Project was removed before directory change");
            const real = await fs.realpath(root);
            if (!(await fs.stat(real)).isDirectory())
              throw Error("Project root must be a directory");
            const canonical = (value) =>
              process.platform === "win32" ? value.toLowerCase() : value;
            if (
              this.projects.some(
                (other) =>
                  other.id !== id && canonical(other.root) === canonical(real),
              )
            )
              throw Error("Project directory already exists");
            oldSession = {
              sessionId: p.sessionId,
              sessionUncertain: p.sessionUncertain,
              adoptedRevision: p.adoptedRevision,
            };
            await prepare(oldRoot, real);
            p.root = real;
            p.sessionId = null;
            p.sessionUncertain = false;
            p.adoptedRevision = 0;
            s.resetEpoch++;
            s.reason =
              "用户切换了项目目录；从新会话开始，先读取最新 progress.md 并继续已发布目标";
            await this._save();
          },
          true,
        );
        p.desiredRunning = wasRunning;
        p.status = wasRunning && !this.closed ? "running" : "paused";
        p.error = null;
        this._syncRunTimer(p);
        await this._save();
        return this.snapshot().find((project) => project.id === id);
      } catch (error) {
        p.root = oldRoot;
        if (oldSession) Object.assign(p, oldSession);
        p.desiredRunning = false;
        p.status = s.handle ? "stopping" : "paused";
        this._syncRunTimer(p);
        p.error = {
          message: `项目目录切换失败，保留原目录并暂停：${redact(error.message)}`,
          count: 1,
          at: new Date().toISOString(),
        };
        await this._save().catch(() => {});
        throw error;
      } finally {
        s.directoryChanging = false;
        this._changed();
        this._kick(p);
      }
    });
  }
  _control(p, mutate, after = async () => {}, directoryChange = false) {
    const s = this._state(p);
    if (s.directoryChanging && !directoryChange)
      throw Error("项目目录正在切换，请稍后重试操作");
    mutate(s);
    this._syncRunTimer(p);
    s.generation++;
    s.pending++;
    s.wake?.();
    // Attach rejection handling immediately: another control may still own the queue.
    const saved = this._save().then(
      () => null,
      (error) => error,
    );
    this._changed();
    const op = s.queue
      .then(async () => {
        const saveError = await saved;
        if (saveError) {
          // A failed disk write cannot make a new run safe. Stop locally and make
          // the unpersisted intent explicit; a later control/shutdown may retry.
          p.desiredRunning = false;
          this._syncRunTimer(p);
          if (s.handle)
            await this.terminateProcess(s.handle.record, { trusted: true });
          if (s.loop) await s.loop;
          s.handle = null;
          p.owner = null;
          p.status = "paused";
          p.error = {
            message: `运行意图保存失败，已停止本地执行；重启可能恢复旧意图：${redact(saveError.message)}`,
            count: 1,
            at: new Date().toISOString(),
          };
          throw saveError;
        }
        if (s.handle)
          await this.terminateProcess(s.handle.record, { trusted: true });
        if (s.loop) await s.loop;
        await after();
      })
      .catch((error) => {
        if (s.handle) {
          p.status = "stopping";
          p.error = {
            message: `无法确认受管理进程树已停止：${redact(error.message)}`,
            count: 1,
            at: new Date().toISOString(),
          };
          this._save().catch(() => {});
        }
        throw error;
      });
    s.queue = op.catch(() => {});
    return op.finally(() => {
      s.pending--;
      if (!s.pending) this._kick(p);
      this._changed();
    });
  }
  async start(id) {
    if (this.closed) throw Error("Runner is shut down");
    const p = this._project(id);
    if (!p.publishedGoal.trim()) throw Error("Publish a goal before starting");
    if (p.desiredRunning) return;
    return this._control(p, (s) => {
      p.desiredRunning = true;
      p.status = "running";
      s.reason = "请先读取 goal.md 执行；如果 progress.md 有跑偏，按照 goal.md 来执行";
    });
  }
  async pause(id) {
    const p = this._project(id);
    return this._control(p, () => {
      p.desiredRunning = false;
      p.status = "paused";
    });
  }
  async publish(id, text) {
    if (typeof text !== "string" || Buffer.byteLength(text) > 1024 * 1024)
      throw Error("Goal must be text under 1 MiB");
    const p = this._project(id);
    return this._control(p, (s) => {
      p.publishedGoal = text;
      p.publishedRevision++;
      if (p.desiredRunning) p.status = "switching";
      s.reason = "用户刚发布新目标，以以下最新目标为准";
    });
  }
  async reset(id) {
    const p = this._project(id);
    return this._control(
      p,
      (s) => {
        s.resetEpoch++;
        p.sessionId = null;
        p.sessionUncertain = false;
        s.reason = "请先读取 goal.md 执行；如果 progress.md 有跑偏，按照 goal.md 来执行";
        if (p.desiredRunning) p.status = "switching";
      },
      async () => {
        p.sessionId = null;
        await this._save();
      },
    );
  }
  async setResources(id, ids) {
    if (
      !Array.isArray(ids) ||
      ids.length > 100 ||
      ids.some((x) => typeof x !== "string")
    )
      throw Error("Invalid resources");
    const p = this._project(id);
    return this._control(p, (s) => {
      p.resourceIds = [...new Set(ids)];
      s.reason = "用户更新了可用资源，请继续当前目标";
    });
  }
  async remove(id) {
    const p = this._project(id);
    return this._control(
      p,
      () => {
        p.desiredRunning = false;
        p.status = "paused";
      },
      async () => {
        this.projects = this.projects.filter((x) => x.id !== id);
        await this._save();
        this.states.delete(id);
      },
    );
  }
  _kick(p) {
    if (this.closed || !p.desiredRunning || !this.projects.includes(p)) return;
    const s = this._state(p);
    if (s.loop || s.pending || s.directoryChanging) return;
    s.loop = this._loop(p, s)
      .catch(async (e) => {
        p.error = {
          message: redact(e.message),
          count: (p.error?.count || 0) + 1,
          at: new Date().toISOString(),
        };
        p.status = "retrying";
        this._changed();
        await new Promise((resolve) => {
          const timer = setTimeout(() => {
            s.wake = null;
            resolve();
          }, 250);
          s.wake = () => {
            clearTimeout(timer);
            s.wake = null;
            resolve();
          };
        });
      })
      .finally(() => {
        s.loop = null;
        if (!s.pending && !this.closed && p.desiredRunning)
          setImmediate(() => this._kick(p));
      });
  }
  async _loop(p, s) {
    while (!this.closed && p.desiredRunning && !s.pending) {
      const generation = s.generation;
      const resetEpoch = s.resetEpoch;
      const started = Date.now();
      let result;
      try {
        // A previous stop may have failed. Never overwrite its ownership record
        // or create another writer until the entire previous tree is gone.
        if (s.handle) {
          await this.terminateProcess(s.handle.record, { trusted: true });
          await s.handle.done;
          s.handle = null;
          p.owner = null;
          await this._save();
        }
        if (p.sessionUncertain)
          throw Error("CLI 未返回明确 session 会话 ID；请重置上下文后继续");
        const spec = await this.adapterFactory(structuredClone(p));
        const resources = await this.resourcesPrompt(structuredClone(p));
        spec.env = await this.executionEnv(structuredClone(p));
        spec.redactionSecrets = await this.outputSecrets(structuredClone(p));
        if (s.pending || generation !== s.generation) break;
        const prompt = [
          this.principles,
          "# 当前已发布目标",
          p.publishedGoal,
          "# 已选择资源",
          resources,
          "# 控制提示",
          s.reason,
        ].join("\n\n");
        const token = randomUUID();
        p.owner = { pid: null, token };
        await this._save();
        if (s.pending || generation !== s.generation) {
          p.owner = null;
          await this._save();
          break;
        }
        const h = launchOwned(spec, p.root, prompt, token, (e) => {
          if (e.type === "output" && Array.isArray(e.entries)) {
            this.emit("output", p.id, e.entries);
            return;
          }
          // Publishing/pausing must retain the session established by this
          // invocation while it is being interrupted. Only reset invalidates it.
          if (resetEpoch !== s.resetEpoch) return;
          if (e.type === "session" && typeof e.id === "string") {
            p.sessionId = e.id;
            this._save().catch(() => {});
            this._changed();
          }
        });
        s.handle = h;
        p.owner = h.record;
        await this._save();
        if (s.pending || generation !== s.generation) {
          await this.terminateProcess(h.record, { trusted: true });
        } else {
          p.adoptedRevision = p.publishedRevision;
          p.status = "running";
          await this._save();
          h.send();
          this.emit("output", p.id, [
            {
              kind: "status",
              text: `${p.backend === "claude" ? "Claude Code" : "Codex"} · ${s.reason}`,
            },
          ]);
          this._changed();
        }
        result = await h.done;
        await this.terminateProcess(h.record, { trusted: true });
        if (
          h.sent &&
          !p.sessionId &&
          resetEpoch === s.resetEpoch &&
          (generation !== s.generation || this.closed)
        ) {
          p.sessionUncertain = true;
          p.error = {
            message: "调用中断前未确认 session 会话 ID；请重置上下文后继续",
            count: 1,
            at: new Date().toISOString(),
          };
        }
        s.handle = null;
        p.owner = null;
        await this._save();
      } catch (e) {
        result = { code: 1, error: e.message };
        if (s.handle) {
          await this.terminateProcess(s.handle.record, { trusted: true });
          s.handle = null;
          p.owner = null;
          await this._save();
        }
      }
      if (
        generation !== s.generation ||
        s.pending ||
        !p.desiredRunning ||
        this.closed
      )
        break;
      if (result.code === 0 && !p.sessionId) {
        p.sessionUncertain = true;
        result.error =
          "CLI 正常退出但未返回 session 会话 ID；请重置上下文，避免静默丢失历史";
      }
      if (result.code !== 0 || result.error) {
        const message = redact(
          result.error || `CLI exited with code ${result.code}`,
        );
        p.error = {
          message,
          count: p.error?.message === message ? p.error.count + 1 : 1,
          at: new Date().toISOString(),
        };
        p.status = "retrying";
        await this._save();
        this._changed();
        if (Date.now() - started < 1000)
          await new Promise((resolve) => {
            const timer = setTimeout(() => {
              s.wake = null;
              resolve();
            }, 250);
            s.wake = () => {
              clearTimeout(timer);
              s.wake = null;
              resolve();
            };
          });
      } else {
        p.error = null;
        s.reason =
          "正常续跑：即使自评为 100% 或上一轮称已完成，也继续围绕当前目标工作";
        this._changed();
      }
    }
  }
  async shutdown({ preserveIntent = false } = {}) {
    if (this.closed && !this.locked) return;
    this.closed = true;
    clearInterval(this.runtimeCheckpoint);
    await this.directoryQueue;
    await Promise.all(
      this.projects.map((p) =>
        this._control(p, () => {
          if (!preserveIntent) p.desiredRunning = false;
          p.status = "paused";
        }),
      ),
    );
    await this.saves;
    if (this.locked) {
      if (this.lockServer) {
        await new Promise((resolve, reject) =>
          this.lockServer.close((e) => (e ? reject(e) : resolve())),
        );
        this.lockServer = null;
      } else await fs.rm(this.lock, { recursive: true, force: true });
      this.locked = false;
    }
  }
}
module.exports = { Runner };
