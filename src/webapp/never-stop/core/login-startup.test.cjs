const test = require("node:test");
const assert = require("node:assert/strict");
const { createLoginStartup } = require("./login-startup.cjs");

function registeredItems(calls) {
  const last = calls.at(-1);
  return {
    command: last?.openAtLogin
      ? [last.path, ...last.args].map((arg) => `"${arg}"`).join(" ")
      : null,
    approved: last?.enabled !== false,
  };
}

function setup(overrides = {}) {
  const calls = [];
  const app = {
    isPackaged: true,
    setLoginItemSettings: (value) => calls.push(value),
    getLoginItemSettings: () => ({ launchItems: [] }),
  };
  const startup = createLoginStartup({
    app,
    platform: "win32",
    env: {},
    execPath: "C:\\temporary\\NeverStop.exe",
    entryFile: "C:\\dev\\main.cjs",
    readWindowsApproval: async () => null,
    readWindowsRegistration: async () => registeredItems(calls),
    ...overrides,
  });
  return { startup, calls, app };
}

test("upgrade replaces stable registration with portable executable and preserves OS disabled state", async () => {
  const names = [];
  const { startup, calls } = setup({
    env: { PORTABLE_EXECUTABLE_FILE: "C:\\Apps\\Never Stop 78.exe" },
    readWindowsApproval: async (name) => {
      names.push(name);
      return false;
    },
  });
  await startup.reconcile({ launchAtLogin: true });
  assert.deepEqual(names, ["com.vantage.never-stop"]);
  assert.deepEqual(calls, [
    {
      name: "com.vantage.never-stop",
      openAtLogin: true,
      enabled: false,
      path: "C:\\Apps\\Never Stop 78.exe",
      args: ["--background"],
    },
  ]);
});

test("disabled preference, development reconciliation and isolated instance never register", async () => {
  for (const options of [
    {},
    {
      app: {
        isPackaged: false,
        setLoginItemSettings() {
          throw Error("unexpected");
        },
      },
    },
    { env: { NEVER_STOP_DATA_DIR: "C:\\isolated" } },
    { enabled: false },
  ]) {
    const { startup, calls } = setup(options);
    await startup.reconcile({ launchAtLogin: Object.keys(options).length > 0 });
    assert.equal(calls.length, 0);
    if (options.env || options.enabled === false) {
      await startup.apply({ launchAtLogin: true });
      await startup.apply({ launchAtLogin: false });
      assert.equal(calls.length, 0);
    }
  }
});

test("explicit development apply passes entry file and disabling does not inspect approval", async () => {
  const calls = [];
  const { startup } = setup({
    app: {
      isPackaged: false,
      setLoginItemSettings: (value) => calls.push(value),
      getLoginItemSettings: () => registeredItems(calls),
    },
    name: "test.random",
    readWindowsRegistration: async () => registeredItems(calls),
    readWindowsApproval: async () => true,
  });
  await startup.apply({ launchAtLogin: true });
  assert.deepEqual(calls[0].args, ["C:\\dev\\main.cjs", "--background"]);
  assert.equal(calls[0].enabled, true);
  assert.equal(calls[0].name, "test.random");
  const disabled = setup({
    readWindowsApproval: async () => {
      throw Error("must not inspect");
    },
  });
  await disabled.startup.apply({ launchAtLogin: false });
  assert.equal(disabled.calls[0].openAtLogin, false);
});

test("silent native write failures and mismatched registration cannot report success", async () => {
  for (const item of [
    { command: null, approved: true },
    { command: '"C:\\old\\NeverStop.exe" --background', approved: true },
    { command: '"C:\\temporary\\NeverStop.exe" --background', approved: false },
    { command: '"C:\\temporary\\NeverStop.exe"', approved: true },
  ]) {
    const { startup } = setup({
      readWindowsRegistration: async () => item,
      app: {
        isPackaged: true,
        setLoginItemSettings() {},
        getLoginItemSettings: () => ({ launchItems: item ? [item] : [] }),
      },
    });
    await assert.rejects(
      startup.apply({ launchAtLogin: true }),
      /自启设置未能验证/,
    );
  }
  const { startup } = setup({
    readWindowsRegistration: async () => ({
      command: '"C:\\old\\NeverStop.exe" --background',
      approved: true,
    }),
    app: {
      isPackaged: true,
      setLoginItemSettings() {},
      getLoginItemSettings: () => ({
        launchItems: [{ name: "com.vantage.never-stop", scope: "user" }],
      }),
    },
  });
  await assert.rejects(
    startup.apply({ launchAtLogin: false }),
    /自启设置未能验证/,
  );
});

test("approval read and registration failures propagate without unsafe registration", async () => {
  const { startup, calls } = setup({
    readWindowsApproval: async () => {
      throw Error("registry denied");
    },
  });
  await assert.rejects(
    startup.reconcile({ launchAtLogin: true }),
    /registry denied/,
  );
  assert.deepEqual(calls, []);
  const failed = setup({
    app: {
      isPackaged: true,
      setLoginItemSettings() {
        throw Error("registration failed");
      },
    },
  });
  await assert.rejects(
    failed.startup.reconcile({ launchAtLogin: true }),
    /registration failed/,
  );
});
