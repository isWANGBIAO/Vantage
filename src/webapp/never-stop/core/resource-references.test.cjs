const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { Runner } = require("./runner.cjs");
const { ResourceStore } = require("./resources.cjs");
const { Application } = require("./application.cjs");

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "never-stop-references-"));
  const dataDir = path.join(root, "data");
  let runner;
  const resources = await new ResourceStore({ dataDir, home: root }).init();
  const restart = async () => {
    if (runner) await runner.shutdown();
    runner = await new Runner({ dataDir, adapterFactory: () => { throw Error("No external agents permitted"); } }).init();
    const app = new Application({ runner, resources, dataDir });
    await app.init();
    return app;
  };
  const app = await restart();
  t.after(async () => { await runner.shutdown(); await fs.rm(root, { recursive: true, force: true }); });
  const projects = [];
  for (const name of ["one", "two"]) {
    const directory = path.join(root, name);
    await fs.mkdir(directory);
    projects.push(await app.invoke("project.add", { root: directory, backend: "codex", name }));
  }
  const a = await app.invoke("resources.save", { resource: { name: "A", host: "a.example.invalid" } });
  const b = await app.invoke("resources.save", { resource: { name: "B", host: "b.example.invalid" } });
  for (const project of projects) await app.invoke("project.resources", { id: project.id, resourceIds: [a.id, b.id] });
  return { app, resources, projects, a, b, runner, restart, dataDir };
}

test("resource deletion removes all references and selections remain usable after restart", async (t) => {
  const { app, projects, a, b, restart, dataDir } = await fixture(t);
  await app.invoke("resources.remove", { id: a.id });
  for (const project of (await app.invoke("state")).projects) assert.deepEqual(project.resourceIds, [b.id]);
  const disk = JSON.parse(await fs.readFile(path.join(dataDir, "projects.json"), "utf8"));
  for (const project of disk) assert.deepEqual(project.resourceIds, [b.id]);
  const restored = await restart();
  const c = await restored.invoke("resources.save", { resource: { name: "C", host: "c.example.invalid" } });
  await restored.invoke("project.resources", { id: projects[0].id, resourceIds: [] });
  await restored.invoke("project.resources", { id: projects[1].id, resourceIds: [b.id, c.id] });
  await restored.invoke("resources.remove", { id: a.id });
});

test("failed resource deletion restores references and permits retry", async (t) => {
  const { app, resources, a, b, dataDir } = await fixture(t);
  const persist = resources.persist.bind(resources);
  resources.persist = async () => { throw Object.assign(Error("synthetic disk full"), { code: "ENOSPC" }); };
  await assert.rejects(app.invoke("resources.remove", { id: a.id }), /disk full/);
  resources.persist = persist;
  assert(resources.list().some((resource) => resource.id === a.id));
  for (const project of (await app.invoke("state")).projects) assert.deepEqual(project.resourceIds, [a.id, b.id]);
  for (const project of JSON.parse(await fs.readFile(path.join(dataDir, "projects.json"), "utf8"))) assert.deepEqual(project.resourceIds, [a.id, b.id]);
  await app.invoke("resources.remove", { id: a.id });
});

test("failed reference persistence does not delete resource or retain a partial selection", async (t) => {
  const { app, resources, runner, a, b } = await fixture(t);
  const save = runner._save.bind(runner);
  let writes = 0;
  runner._save = () => ++writes === 2 ? Promise.reject(Error("synthetic reference failure")) : save();
  await assert.rejects(app.invoke("resources.remove", { id: a.id }), /reference failure/);
  runner._save = save;
  assert(resources.list().some((resource) => resource.id === a.id));
  for (const project of runner.snapshot()) assert.deepEqual(project.resourceIds, [a.id, b.id]);
});

test("resource selection and deletion are serialized and cannot persist dangling ids", async (t) => {
  const { app, projects, a, b } = await fixture(t);
  const results = await Promise.allSettled([
    app.invoke("resources.remove", { id: a.id }),
    app.invoke("project.resources", { id: projects[0].id, resourceIds: [a.id, b.id] }),
  ]);
  assert.equal(results[0].status, "fulfilled");
  assert.equal(results[1].status, "rejected");
  for (const project of (await app.invoke("state")).projects) assert.deepEqual(project.resourceIds, [b.id]);
});

test("startup repairs historical dangling references and reports the repair", async (t) => {
  const { app, resources, projects, a, b, restart } = await fixture(t);
  await resources.remove(a.id); // Simulate a record written by the old version.
  const restored = await restart();
  const state = await restored.invoke("state");
  assert.equal(state.resourceWarnings.length, projects.length);
  for (const project of state.projects) assert.deepEqual(project.resourceIds, [b.id]);
  assert.equal((await app.invoke("state")).resources.some((resource) => resource.id === a.id), false);
});
