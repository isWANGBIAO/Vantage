# Local Crash Recording Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collect local crash evidence for the Electron client and Python backend, with bounded retention, interruption notice and diagnostics access.

**Architecture:** Crashpad captures native Electron faults; faulthandler captures Python fatal stacks. A local session/incident store tracks interrupted startup and backend exits without recording prompts or credentials. The renderer uses a narrow native capability to read status and open the local directory.

**Tech Stack:** Electron/Node, React, Python standard library, pytest and node:test.

### Task 1: Electron collection and lifecycle

Files: `src/webapp/src/utils/crashDiagnostics.cjs`, matching `.test.js`,
`src/webapp/main.cjs`, `src/webapp/src/utils/backendRuntime.cjs` as needed.

1. Write failing tests for local-only crashReporter options, process markers,
   interrupted/clean startup and ten-record/200 MiB retention.
2. Run `node --test src/webapp/src/utils/crashDiagnostics.test.js` and observe failure.
3. Implement the module, initialize only in the primary app before windows,
   record renderer/child/backend abnormal exits; add narrow status/open handlers.
4. Verify tests and a real isolated Electron `process.crash()` generates a dump.

### Task 2: Python collection

Files: `src/core/crash_diagnostics.py`, `src/scripts/run_server_background.py`
(verified packaging entry), `tests/test_crash_diagnostics.py`.

1. Write failing tests for configured data-root storage, no-value tracebacks,
   fatal faulthandler output, process isolation and active-file-safe retention.
2. Run `python -m pytest -q tests/test_crash_diagnostics.py` and observe failure.
3. Install diagnostics at packaged entry before service imports and in child modes.
4. Verify uncaught exceptions and isolated native fatal faults write useful stacks.

### Task 3: UI and documentation

Files: `src/webapp/preload.cjs`, `src/webapp/src/components/Settings.jsx`,
`src/webapp/src/App.jsx`, `src/webapp/src/utils/displayCopy.js`, matching tests.

1. Add failing tests for native capability isolation and bilingual privacy copy.
2. Expose status `{localOnly, directory, previousInterrupted, retention}` and open
   diagnostics without allowing arbitrary filesystem targets.
3. Show a non-blocking next-start interruption notice and Settings access button.
4. Run frontend lint/tests/build and isolated production Electron UI smoke.

### Task 4: Review and delivery

1. Review requirements/diffs and fix all important issues.
2. Run full Python suite and frontend `check`; document isolated crash smoke.
3. Bump main app release (Never Stop version unchanged), commit detailed scope.
4. Let `RUN.bat` finish naturally; verify installed metadata, backend and native
   diagnostics status. Do not crash the real user session or upload diagnostics.
5. Keep this branch local, do not push. Preserve unrelated untracked native files.
