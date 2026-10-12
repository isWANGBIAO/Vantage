# Never Stop Vantage Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver Never Stop inside the Vantage app as one navigable page and one packaged application, while preserving existing project data.

**Architecture:** Vantage's Electron main process owns a single Never Stop service and exposes its allowlisted operations through the existing secure preload. The React app lazy-loads the Never Stop view into a Shadow DOM host to isolate styles. A one-time, copy-first migration moves legacy data under Vantage's configured user data directory.

**Tech Stack:** Electron, React, Vite, Node.js `node:test`, Windows NSIS packaging.

---

### Task 1: Bring the latest Never Stop business core into main

**Files:** `src/webapp/never-stop/core/principles.cjs`, `application.cjs`, `runner.cjs`, their focused tests, `ui/App.jsx`, `ui/style.css`.

1. Add the feature branch's tests for editable principles, failed project mutation rollback, and published goal priority. Run focused `node --test` and confirm the new tests fail on the main baseline.
2. Port the corresponding core code from `feature/never-stop-demo` without copying standalone shell/icon/login startup changes. Run focused tests and confirm they pass.
3. Commit with a detailed description of the imported behavior and source branch commits.

### Task 2: Migrate legacy data safely

**Files:** new `src/webapp/never-stop/core/data-migration.cjs` and `.test.cjs`.

1. Write failing tests for absent source, successful copy of projects/settings/resources/principles, no destination overwrite, copy verification failure, and active legacy runner refusal.
2. Implement copy to a staging directory under `<runtimePaths.dataDir>/never-stop`, byte verification, then atomic rename. Keep the source intact, do not move project folders, and release the legacy lock in every path.
3. Run the focused test, commit with migration behavior and limitations.

### Task 3: Own the runner from Vantage's main process

**Files:** new `src/webapp/never-stop/core/vantage-service.cjs` and test; `src/webapp/main.cjs`, `src/webapp/preload.cjs`, `src/webapp/main.test.js`.

1. Write failing service and main/preload tests: one owner, trusted main-frame IPC, page-independent lifetime, explicit shutdown preserving run intent, initialization failure isolated to Never Stop.
2. Extract the existing standalone initialization into an Electron-independent service factory where practical. Initialize it once after app readiness; bridge `never-stop:invoke` and change events through the Vantage window; keep Vantage's existing tray/window behavior.
3. Integrate migration before service initialization. Disable the legacy startup entry after verified migration without changing the Vantage startup preference.
4. Run focused service/main tests and commit.

### Task 4: Add one Vantage page

**Files:** `src/webapp/src/App.jsx`, `App.test.js`, `src/utils/displayCopy.js`, new `src/components/NeverStopPage.jsx`, `src/webapp/never-stop/ui/App.jsx` and related tests.

1. Write failing tests for `#never-stop` navigation, lazy mount, tab switch preserving drafts, no polling while hidden, and a visible local error when the desktop bridge is unavailable.
2. Render the existing Never Stop view in a Shadow DOM host. Keep it mounted after first visit and pass visibility to pause UI polling; leave background runner in the main process.
3. Replace standalone Demo copy and duplicate startup controls with the Vantage page model. Run focused tests and commit.

### Task 5: Ship only the unified application

**Files:** `src/webapp/package.json`, `package.test.js`, `vite.config.*`, `README.md`, `RUN.bat`, `NEVER_STOP.bat`, standalone entry/build files and tests as applicable.

1. Write failing package contract tests for included Never Stop core/principles, absence of separate product scripts, and actual production asset loading.
2. Remove separate Never Stop launch/package entry points while retaining `never-stop:test`. Add core/principles to the Vantage package whitelist; update documentation and CI to test integrated behavior.
3. Run `npm --prefix src/webapp run lint`, `test`, `build`, `never-stop:test`; inspect package contents and run available Electron smoke checks. Commit.

### Task 6: Integrate and verify

1. Review the complete diff for private data and unrelated branch content. Run the relevant source tests again from the integration branch.
2. Merge the integration branch into local `main`, rerun the critical checks there, and report the resulting commits and unpushed status. Preserve the dirty `feature/never-stop-demo` checkout and all its unrelated work.
