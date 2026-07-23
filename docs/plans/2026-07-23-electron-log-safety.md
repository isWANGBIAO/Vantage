# Electron Log Safety Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent broken Electron console pipes from recursively filling disk and keep all Electron logs within a deterministic retention budget.

**Architecture:** Extract main-process logging into a dependency-free CommonJS utility that performs bounded synchronous file writes and best-effort console mirroring. The logger rotates before an append would exceed the configured file limit, prunes matching Electron logs to a global file-count limit, and bounds oversized legacy logs during construction.

**Tech Stack:** Node.js CommonJS, built-in `fs`/`path`, Node test runner, Electron main process.

---

### Task 1: Add the failing broken-pipe regression test

**Files:**
- Create: `src/webapp/src/utils/boundedLogger.test.js`
- Create after RED: `src/webapp/src/utils/boundedLogger.cjs`

**Step 1: Write the failing test**

Create a temporary directory and a console stub whose `log()` method throws an
error with `code = "EPIPE"`. Use the desired API:

```js
const logger = createBoundedLogger({
  logFile,
  consoleObject: brokenConsole,
  maxBytes: 1024,
  maxFiles: 3,
});

assert.doesNotThrow(() => logger.info('first'));
assert.doesNotThrow(() => logger.info('second'));
assert.equal(consoleCalls, 1);
assert.match(readFileSync(logFile, 'utf8'), /first[\s\S]*second/);
```

**Step 2: Run the test to verify it fails**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: FAIL because `boundedLogger.cjs` does not exist.

**Step 3: Implement the minimal safe logger**

Export `createBoundedLogger()`. Build entries with the existing timestamp and
level format, append synchronously, and wrap console mirroring in `try/catch`.
After any console failure, disable future console mirroring. Never call the
application logger from the fallback path.

**Step 4: Run the test to verify it passes**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: 1 test passes.

**Step 5: Commit**

```powershell
git add src/webapp/src/utils/boundedLogger.cjs src/webapp/src/utils/boundedLogger.test.js
git commit -m "test: reproduce Electron EPIPE log recursion"
```

### Task 2: Add hard size and retention limits

**Files:**
- Modify: `src/webapp/src/utils/boundedLogger.test.js`
- Modify: `src/webapp/src/utils/boundedLogger.cjs`

**Step 1: Write failing rotation tests**

Use small injected limits to verify:

- every matching Electron log is at most `maxBytes`;
- the total matching file count is at most `maxFiles`;
- the newest entry remains available after rotation;
- a single oversized entry cannot create an oversized file.

**Step 2: Run the tests to verify RED**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: FAIL because the active file grows past the injected limit.

**Step 3: Implement bounded rotation**

Before each append:

1. encode the entry once as UTF-8;
2. bound a single oversized entry to the newest `maxBytes` of content;
3. rotate the active file when current size plus pending bytes exceeds
   `maxBytes`;
4. prune all matching `electron*.log*` files by modification time until no more
   than `maxFiles` remain.

The production defaults are `10 * 1024 * 1024` bytes and six total files (one
active file plus five retained files).

**Step 4: Run the tests to verify GREEN**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: all logger tests pass and every fixture file stays within its limit.

### Task 3: Bound legacy logs safely at startup

**Files:**
- Modify: `src/webapp/src/utils/boundedLogger.test.js`
- Modify: `src/webapp/src/utils/boundedLogger.cjs`

**Step 1: Write failing startup-cleanup tests**

Pre-create multiple matching Electron logs, including an oversized legacy daily
log, plus an unrelated `server` log. Construct the logger and assert:

- matching files are individually bounded;
- no more than `maxFiles` matching files remain;
- the newest tail of the oversized log is preserved;
- the unrelated server log is unchanged.

**Step 2: Run the tests to verify RED**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: FAIL because startup cleanup is not implemented.

**Step 3: Implement startup cleanup**

Scan only the configured log directory and only names matching
`electron*.log*`. For an oversized matching file, replace it atomically with
its newest `maxBytes` bytes. Then prune the oldest matching files to
`maxFiles`. Ignore disappeared files so concurrent cleanup does not crash
startup.

**Step 4: Run the tests to verify GREEN**

Run:

```powershell
node --test src/utils/boundedLogger.test.js
```

Expected: all logger tests pass.

### Task 4: Integrate the bounded logger into Electron

**Files:**
- Modify: `src/webapp/main.cjs:14-18`
- Modify: `src/webapp/main.cjs:47-49`
- Modify: `src/webapp/main.cjs:112-134`
- Modify: `src/webapp/package.test.js`

**Step 1: Write a failing packaging-contract test**

Assert that `main.cjs` imports `createBoundedLogger`, no longer contains direct
`console.log(logEntry)` or `console.error(logEntry)` calls, and constructs the
logger for the configured Electron log file.

**Step 2: Run the contract test to verify RED**

Run:

```powershell
node --test package.test.js
```

Expected: FAIL because `main.cjs` still contains the recursive logger.

**Step 3: Replace the inline logger**

Import `createBoundedLogger` from `src/utils/boundedLogger.cjs`, construct it
with `logFile`, and keep all existing `log.info`, `log.warn`, and `log.error`
call sites unchanged.

**Step 4: Run focused and full Node tests**

Run:

```powershell
node --test package.test.js src/utils/boundedLogger.test.js
npm test
```

Expected: focused tests pass; full suite reports zero failures.

**Step 5: Commit**

```powershell
git add src/webapp/main.cjs src/webapp/package.test.js src/webapp/src/utils/boundedLogger.cjs src/webapp/src/utils/boundedLogger.test.js
git commit -m "fix: bound Electron logs and isolate broken pipes"
```

### Task 5: Verify quality and package behavior

**Files:**
- No intended source changes.

**Step 1: Run the full webapp check**

Run:

```powershell
npm run check
```

Expected: lint, all Node tests, and the production Vite build pass.

**Step 2: Run the original failure simulation**

Launch a small Node harness that constructs the production logger with a console
method throwing `EPIPE`, writes repeated exceptions, and asserts:

- the process exits normally;
- the active and rotated files remain within the production limits;
- repeated entries are retained without recursive growth.

**Step 3: Review the diff**

Run:

```powershell
git diff main...HEAD --check
git diff main...HEAD --stat
```

Expected: no whitespace errors and only the design, plan, logger, integration,
and tests are changed.

### Task 6: Build, install, and verify the Windows application

**Files:**
- Expected generated version metadata may change through the repository's
  release flow.

**Step 1: Run the full supported Windows flow**

From the repository root:

```powershell
.\RUN.bat
```

Allow the command to finish naturally.

Expected: backend build, frontend build, installer, installation, and launch
all complete successfully.

**Step 2: Verify installed source identity**

Read the installed `app.asar` and confirm:

- the installed package version matches the built version;
- installed `main.cjs` imports the bounded logger;
- installed `boundedLogger.cjs` matches the branch artifact.

**Step 3: Verify real runtime log bounds**

Launch the installed app, exercise hide/restore, and run a controlled
broken-output-pipe launch. Confirm no `EPIPE` recursion and no Electron log
exceeds 10 MiB.

**Step 4: Commit generated release metadata if tracked**

Use a detailed commit message that records the version/build metadata produced
by the supported release flow.

### Task 7: Final review and publication

**Files:**
- Review all branch changes.

**Step 1: Request an independent code review**

Use the requesting-code-review skill and address all actionable findings.

**Step 2: Re-run verification after review changes**

Run focused logger tests, `npm run check`, and the installed runtime smoke test.

**Step 3: Push the branch**

```powershell
git push -u origin feature/fix-electron-log-recursion
```

Expected: the remote branch points to the verified local tip.
