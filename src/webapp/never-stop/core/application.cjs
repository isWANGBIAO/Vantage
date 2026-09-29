const { EventEmitter } = require("node:events");
const path = require("node:path");
const { atomicWrite, readText } = require("./files.cjs");
class Application extends EventEmitter {
  constructor({
    runner,
    files,
    dataDir,
    resources,
    principles,
    discover,
    pickDirectory,
    applySettings,
    testNotification,
    output,
    reconcileStartup,
    appVersion,
  }) {
    super();
    Object.assign(this, {
      runner,
      files,
      dataDir,
      resources,
      principles,
      discover,
      pickDirectory,
      applySettings,
      testNotification,
      output,
      reconcileStartup,
      appVersion,
    });
    this.settings = {
      notificationTime: "20:00",
      notificationsEnabled: false,
      launchAtLogin: false,
    };
    runner.on("change", () => this.emit("change"));
    this.settingsQueue = Promise.resolve();
    this.projectFileQueues = new Map();
  }
  async init() {
    const raw = await readText(path.join(this.dataDir, "settings.json"));
    if (raw) this.settings = { ...this.settings, ...JSON.parse(raw) };
    delete this.settings.startupError;
    try { await this.reconcileStartup?.(this.settings); }
    catch (error) { this.settings.startupError = String(error.message).slice(0, 1000); }
  }
  project(id) {
    const project = this.runner.snapshot().find((p) => p.id === id);
    if (!project) throw new Error("项目不存在");
    return project;
  }
  async invoke(method, payload = {}) {
    if (
      [
        "project.directory.change",
        "goal.read",
        "goal.save",
        "goal.publish",
        "progress.read",
      ].includes(method)
    ) {
      const previous =
        this.projectFileQueues.get(payload.id) || Promise.resolve();
      const operation = previous
        .catch(() => {})
        .then(() => this.invokeUnlocked(method, payload));
      this.projectFileQueues.set(payload.id, operation);
      try {
        return await operation;
      } finally {
        if (this.projectFileQueues.get(payload.id) === operation)
          this.projectFileQueues.delete(payload.id);
      }
    }
    return this.invokeUnlocked(method, payload);
  }
  async invokeUnlocked(method, payload = {}) {
    const { id } = payload;
    switch (method) {
      case "state":
        return {
          appVersion: this.appVersion,
          projects: this.runner.snapshot(),
          settings: this.settings,
          resources: this.resources.list(),
          principles: this.principles,
        };
      case "project.pick":
        return this.pickDirectory(Boolean(payload.create));
      case "project.directory.change": {
        const project = this.project(id);
        if (typeof payload.root !== "string" || !payload.root.trim())
          throw new Error("请选择有效目标目录");
        const root = await require("node:fs/promises").realpath(payload.root);
        let preparation = { warnings: [] };
        const changed = await this.files.withDirectoryChange(
          project.root,
          root,
          () =>
            this.runner.changeDirectory(id, root, async (oldRoot, newRoot) => {
              preparation = await this.files.prepareDirectoryChange(
                oldRoot,
                newRoot,
                { publishedGoal: project.publishedGoal },
              );
              return preparation;
            }),
        );
        this.emit("change");
        return { ...changed, directoryWarnings: preparation.warnings };
      }
      case "project.add": {
        const value = await this.runner.addProject(payload);
        this.emit("change");
        return value;
      }
      case "project.start":
        return this.runner.start(id);
      case "project.pause":
        return this.runner.pause(id);
      case "project.reset":
        return this.runner.reset(id);
      case "project.remove":
        return this.runner.remove(id);
      case "project.resources": {
        const available = new Set(this.resources.list().map((r) => r.id));
        if (
          !Array.isArray(payload.resourceIds) ||
          payload.resourceIds.some((r) => !available.has(r))
        )
          throw new Error("资源选择无效");
        return this.runner.setResources(id, payload.resourceIds);
      }
      case "goal.read":
        return this.files.readGoal(this.project(id).root);
      case "goal.save":
        return this.files.saveGoal(
          this.project(id).root,
          payload.text,
          payload.version,
        );
      case "goal.publish": {
        const draft = await this.files.readGoal(this.project(id).root);
        if (draft.text !== payload.text)
          throw new Error("目标编辑冲突：请先保存并核对最新草稿");
        if (!draft.text.trim()) throw new Error("请填写目标后发布");
        return this.runner.publish(id, draft.text);
      }
      case "progress.read":
        return this.files.readProgress(this.project(id).root);
      case "output.read": {
        this.project(id);
        const after =
          Number.isSafeInteger(payload.after) && payload.after >= 0
            ? payload.after
            : 0;
        return this.output.read(id, { after });
      }
      case "output.clear":
        this.project(id);
        this.output.clear(id);
        return true;
      case "resources.save": {
        const result = await this.resources.save(payload.resource);
        this.emit("change");
        return result;
      }
      case "resources.remove": {
        await this.resources.remove(id);
        this.emit("change");
        return true;
      }
      case "resources.import": {
        const result = await this.resources.importSSH();
        this.emit("change");
        return result;
      }
      case "projects.discover":
        return this.discover();
      case "notifications.test":
        return this.testNotification();
      case "settings.save": {
        const pending = this.settingsQueue
          .catch(() => {})
          .then(async () => {
            const patch = payload.settings || {};
            if (
              patch.notificationTime !== undefined &&
              !/^([01]\d|2[0-3]):[0-5]\d$/.test(patch.notificationTime)
            )
              throw new Error("通知时间必须为 HH:mm");
            for (const key of ["notificationsEnabled", "launchAtLogin"])
              if (patch[key] !== undefined && typeof patch[key] !== "boolean")
                throw new Error("设置值必须为布尔类型");
            const next = { ...this.settings };
            for (const key of Object.keys(next))
              if (patch[key] !== undefined) next[key] = patch[key];
            await this.applySettings?.(next);
            delete next.startupError;
            await atomicWrite(
              path.join(this.dataDir, "settings.json"),
              JSON.stringify(next),
            );
            this.settings = next;
            this.emit("change");
            return next;
          });
        this.settingsQueue = pending;
        return pending;
      }
      default:
        throw new Error("不支持的操作");
    }
  }
}
module.exports = { Application };
