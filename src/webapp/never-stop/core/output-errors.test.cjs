const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const { randomUUID } = require("node:crypto");
const { launchOwned, terminateOwned } = require("./process-owner.cjs");

async function runErrorFixture(t, body, secrets = []) {
  const root = await fs.mkdtemp(
    path.join(os.tmpdir(), "never-stop-output-errors-"),
  );
  const fake = path.join(root, "error-cli.cjs");
  await fs.writeFile(
    fake,
    `process.stdin.resume();${body};process.exitCode=1;`,
  );
  const events = [];
  const h = launchOwned(
    { command: process.execPath, args: [fake], redactionSecrets: secrets },
    root,
    "synthetic goal",
    randomUUID(),
    (event) => events.push(event),
  );
  t.after(async () => {
    await terminateOwned(h.record, { trusted: true });
    await fs.rm(root, { recursive: true, force: true });
  });
  h.send();
  const done = await h.done;
  assert.equal(done.code, 1);
  return { done, events };
}

test("worker masks JSON error credentials before the old 1000-character summary boundary", async (t) => {
  const secret = "NEVER_ECHO_BOUNDARY_PASSWORD_824671920";
  const result = await runErrorFixture(
    t,
    `console.log(JSON.stringify({type:'error',message:${JSON.stringify("x".repeat(990) + secret + " suffix")}}))`,
    [secret],
  );
  const visible = JSON.stringify(result);
  assert.ok(!visible.includes(secret));
  assert.ok(!visible.includes("NEVER_ECHO"));
  assert.ok(!visible.includes("824671920"));
  assert.ok(result.done.error.includes("[已隐藏]"));
});
test("worker masks stderr credentials before the old 2048-character raw-tail boundary", async (t) => {
  const secret = "NEVER_ECHO_BOUNDARY_PASSWORD_824671920";
  const result = await runErrorFixture(
    t,
    `console.error(${JSON.stringify("p".repeat(200) + secret + "x".repeat(2030))})`,
    [secret],
  );
  const visible = JSON.stringify(result);
  assert.ok(!visible.includes("NEVER_ECHO"));
  assert.ok(!visible.includes("824671920"));
  assert.ok(result.done.error.includes("[已隐藏]"));
});
test("worker error summary and live output omit a multi-line private-key body longer than its old raw tail", async (t) => {
  const marker = "PRIVATE_KEY_BODY_MUST_NOT_APPEAR_";
  const pem =
    "-----BEGIN OPENSSH PRIVATE KEY-----\n" +
    (marker.repeat(100) + "\n").repeat(2) +
    "-----END OPENSSH PRIVATE KEY-----\n";
  const result = await runErrorFixture(
    t,
    `process.stderr.write(${JSON.stringify(pem)})`,
  );
  const visible = JSON.stringify(result);
  assert.ok(!visible.includes(marker));
  assert.ok(!visible.includes("BODY_MUST_NOT_APPEAR"));
  assert.match(result.done.error, /私钥已隐藏/);
});
