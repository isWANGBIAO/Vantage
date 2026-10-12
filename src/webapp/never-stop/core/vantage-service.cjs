"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const { Runner } = require("./runner.cjs");
const { ProjectFiles, atomicWrite, readText } = require("./files.cjs");
const { Application } = require("./application.cjs");
const { ResourceStore, startResourceBroker } = require("./resources.cjs");
const { discoverProjects } = require("./discovery.cjs");
const { DailyNotifier } = require("./notifications.cjs");
const { BoundedOutput, sanitizeOutput } = require("./live-output.cjs");
const { prepareNeverStopData } = require("./data-migration.cjs");

async function createVantageNeverStopService({
  dataDir,
  legacyDir,
  appVersion = null,
  safeStorage,
  Notification,
  pickDirectory = async () => null,
  testNotification = async () => { throw Error("Notifications are unavailable"); },
  onOpen = () => {},
  onChange = () => {},
  onError = () => {},
  prepareData = prepareNeverStopData,
} = {}) {
  const prepared = await prepareData({ targetDir: dataDir, legacyDir });
  const releaseLegacyLock = prepared.releaseLegacyLock || (async () => {});
  const brokers = new Map();
  let runner;
  let notifier;
  let refreshTimer;
  let broadcastTimer;
  let shutdownPromise;
  let closed = false;

  const broadcast = (change = {}) => {
    if (broadcastTimer) return;
    broadcastTimer = setTimeout(() => {
      broadcastTimer = null;
      onChange(change);
    }, 100);
    broadcastTimer.unref?.();
  };

  async function shutdown({ preserveIntent = true } = {}) {
    if (closed) return;
    if (shutdownPromise) return shutdownPromise;
    shutdownPromise = (async () => {
      clearInterval(refreshTimer);
      clearTimeout(broadcastTimer);
      notifier?.stop();
      await runner?.shutdown({ preserveIntent });
      for (const broker of brokers.values()) await broker.close();
      brokers.clear();
      await releaseLegacyLock();
      closed = true;
    })();
    try {
      await shutdownPromise;
    } catch (error) {
      shutdownPromise = null;
      throw error;
    }
  }

  try {
    await fs.mkdir(dataDir, { recursive: true });
    const principles = await fs.readFile(
      path.join(__dirname, "..", "never_stop_execution_principles_v0_1.md"),
      "utf8",
    );
    const resources = await new ResourceStore({ dataDir, safeStorage }).init();
    const files = new ProjectFiles({ dataDir });
    const output = new BoundedOutput();
    runner = new Runner({
      dataDir,
      principles,
      resourcesPrompt: project => resources.prompt(project.resourceIds),
      outputSecrets: project => (project.resourceIds || []).flatMap(id => {
        if (!resources.list().some(resource => resource.id === id)) return [];
        const resource = resources.credential(id);
        return [resource.password, resource.passphrase].filter(Boolean);
      }),
      executionEnv: async project => {
        if (!brokers.has(project.id)) {
          brokers.set(project.id, await startResourceBroker(resources, {
            allowedIds: () => runner.snapshot().find(item => item.id === project.id)?.resourceIds || [],
          }));
        }
        return brokers.get(project.id).env;
      },
    });
    const outputResourceIds = new Map();
    const updateResourceIds = projects => {
      outputResourceIds.clear();
      for (const project of projects) outputResourceIds.set(project.id, project.resourceIds || []);
    };
    runner.on("change", updateResourceIds);
    runner.on("output", (id, entries) => {
      const resourceIds = outputResourceIds.get(id);
      if (!resourceIds) return;
      try {
        const secrets = [];
        for (const resourceId of resourceIds) {
          if (!resources.list().some(item => item.id === resourceId)) continue;
          const resource = resources.credential(resourceId);
          for (const value of [resource.password, resource.passphrase]) {
            if (value) secrets.push(value);
          }
        }
        output.append(id, entries.map(entry => ({ ...entry, text: sanitizeOutput(entry.text, secrets) })));
      } catch {
        output.append(id, [{ kind: "error", text: "凭据脱敏暂不可用，本批运行输出已隐藏。" }]);
      }
    });

    const application = new Application({
      runner, files, dataDir, resources, principles, output,
      discover: discoverProjects, pickDirectory, testNotification, appVersion,
    });
    await application.init();
    await runner.init();
    updateResourceIds(runner.snapshot());
    application.on("change", () => {
      const ids = new Set(runner.snapshot().map(project => project.id));
      for (const [id, broker] of brokers) {
        if (!ids.has(id)) {
          brokers.delete(id);
          output.remove(id);
          void broker.close().catch(onError);
        }
      }
      broadcast();
    });

    const notificationState = path.join(dataDir, "notifications.json");
    notifier = new DailyNotifier({
      Notification,
      loadState: async () => JSON.parse(await readText(notificationState, "{}")),
      saveState: state => atomicWrite(notificationState, JSON.stringify(state)),
      onOpen,
      onError: error => { application.settings.notificationError = error; broadcast(); },
    });
    notifier.start(
      () => ({ enabled: application.settings.notificationsEnabled, time: application.settings.notificationTime }),
      () => runner.snapshot(),
    );
    let reading = false;
    refreshTimer = setInterval(async () => {
      if (reading || closed) return;
      reading = true;
      try {
        await Promise.allSettled(runner.snapshot().map(project => files.readProgress(project.root)));
        broadcast();
      } catch (error) {
        onError(error);
      } finally {
        reading = false;
      }
    }, 1500);
    refreshTimer.unref?.();

    return {
      invoke: (method, payload) => application.invoke(method, payload),
      shutdown,
      migrated: prepared.migrated,
      legacyResolved: prepared.legacyResolved,
    };
  } catch (error) {
    try {
      await shutdown();
    } catch (cleanupError) {
      onError(cleanupError);
    }
    throw error;
  }
}

module.exports = { createVantageNeverStopService };
