class DailyNotifier {
  constructor({
    Notification,
    loadState = () => ({}),
    saveState = async () => {},
    onOpen = () => {},
    onError = () => {},
  }) {
    Object.assign(this, {
      Notification,
      loadState,
      saveState,
      onOpen,
      onError,
    });
    this.busy = false;
    this.error = null;
    this.active = new Set();
  }
  async tick(settings, projects, now = new Date()) {
    if (this.busy || !settings?.enabled) return;
    this.busy = true;
    try {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(settings.time || ""))
        throw new Error("每日通知时间无效");
      const [hour, minute] = settings.time.split(":").map(Number);
      if (now.getHours() * 60 + now.getMinutes() < hour * 60 + minute) return;
      const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      const state = await this.loadState();
      if (state.lastDay === day) return;
      const running = projects.filter((p) => p.desiredRunning);
      if (!running.length) return;
      if (!this.Notification?.isSupported())
        throw new Error("当前平台不支持原生通知，请检查系统通知权限");
      // Persist the local-day marker before showing; repeated DST hours and restarts cannot duplicate reminders.
      await this.saveState({ ...state, lastDay: day });
      for (const project of running) {
        const retrying = project.status === "retrying";
        const notification = new this.Notification({
          title: "Never Stop",
          body: `${project.name || project.root}：${retrying ? "正在自动重试" : "仍在运行"}。点击打开项目。`,
        });
        this.active.add(notification);
        notification.on("click", () => this.onOpen(project.id));
        notification.on("close", () => this.active.delete(notification));
        notification.on("failed", (_event, error) => {
          this.active.delete(notification);
          this.error = `系统通知发送失败：${error}`;
          this.onError(this.error);
        });
        notification.show();
      }
      this.error = null;
    } catch (e) {
      this.error = e.message;
      this.onError(this.error);
    } finally {
      this.busy = false;
    }
  }
  start(getSettings, getProjects) {
    this.stop();
    this.timer = setInterval(
      () => this.tick(getSettings(), getProjects()),
      15000,
    );
    this.timer.unref?.();
    return this;
  }
  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
module.exports = { DailyNotifier };
