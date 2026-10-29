# Exit Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Leave bounded local exit evidence, or durable interruption evidence on restart, for every observable Vantage shutdown.

**Architecture:** Electron session snapshots plus an external, standard-library observer in the existing backend executable. Native process handles identify Windows processes without PID-reuse ambiguity; heartbeat recovery covers simultaneous writer loss.

**Tech Stack:** Electron/Node, Python standard library, Windows process APIs, PyInstaller, pytest and node:test.

---

### Task 1: Session lifecycle and recovery

Files: `src/webapp/src/utils/crashDiagnostics.cjs`, its `.test.js`, and `main.cjs`.
Write failing tests for old-session identity, durable heartbeat, clean/shutdown
phases, normal and unexpected backend exits, bounded history and write-failure
signals. Run `node --test src/webapp/src/utils/crashDiagnostics.test.js` and confirm
the new assertions fail. Implement atomic, allowlisted lifecycle snapshots and
event files without weakening existing no-symlink/retention rules. Rerun the
tests. Preserve existing incident compatibility. Commit with a detailed message.

### Task 2: External Windows observer

Files: new `src/core/exit_observer.py`, `tests/test_exit_observer.py`, early dispatch
in `src/scripts/run_server_background.py`, and packaging import declarations.
Write failing tests for strict session validation, process-handle identity,
exit-code classification, separate atomic output, bounded retention, launcher
breakaway/fallback and readiness/failure acknowledgement. Verify RED with
`python -m pytest -q tests/test_exit_observer.py`. Implement without heavy service
imports. Run real isolated Windows children, terminate them, assert recorded
codes and timestamps. Never terminate the actual Vantage during synthetic tests.
Rerun entrypoint and packaging regression tests. Commit with detailed evidence.

### Task 3: Integration and full interruption smoke

Files: `src/webapp/main.cjs`, new observer launcher utility/tests, isolated smoke
script, `tests/test_crash_diagnostics.py`, and `src/core/crash_diagnostics.py`.
Test launcher failure and success acknowledgement first. Wire session startup,
backend PID registration, heartbeat and shutdown events. Keep Python interrupted
records instead of silently deleting their only evidence. Test synthetic normal
exit, abnormal code-zero, main/backend force kill, and killing all evidence
writers followed by restart recovery. Check error reporting has no private text.
Run native crash smoke and existing UI tests. Review specification then code
quality before release; repair findings and rerun affected tests.

### Task 4: Release and installed verification

Bump patch version and relevant tracked version tests/docs. Run frontend lint,
tests, build, Never Stop tests, focused Python/packaging tests and isolated native
diagnostic smoke. Integrate the verified commits into the original checkout
without overwriting unrelated work. Run `RUN.bat` to natural completion. Verify
installed version/build and bundled observer, fresh lifecycle heartbeat and
readiness acknowledgement; confirm configuration hashes unchanged. Preserve
private runtime evidence outside Git. Report verified guarantees and limits.
