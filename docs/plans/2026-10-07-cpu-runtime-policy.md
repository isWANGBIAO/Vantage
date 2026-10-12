# CPU Runtime Policy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove implicit OpenCL and Electron hardware acceleration from Vantage.

**Architecture:** A process-local Python bootstrap establishes OpenCL policy before
native imports. Electron applies its supported software-rendering policy before
app readiness. Independent backend and UI changes can run in parallel.

**Tech Stack:** Python, OpenCV, PyInstaller, Electron, pytest, Node test runner.

---

### Task 1: Python policy and entry points

- Inspect `src/scripts/pyinstaller_runtime_hook.py`,
  `src/scripts/run_server_background.py`, `src/server.py`, `src/cli.py`,
  `src/scripts/analyze_face.py`, and direct OpenCV consumers.
- Write `tests/test_cpu_runtime_policy.py`: force an inherited enabling value to
  `disabled`; establish policy before native consumers and in children.
- Run `.venv-backend-runtime-gpu/Scripts/python.exe -m pytest -q tests/test_cpu_runtime_policy.py`
  and confirm expected failures before implementation.
- Create `src/core/cpu_runtime_policy.py`; wire earliest safe process/package
  boundaries and explicit runtime hook before any library bootstrap.
- Repeat targeted and related tests; do not initialize GPU or camera.

### Task 2: Electron startup policy

- Add startup-order regression checks in `src/webapp/main.test.js` using the
  existing main-process harness. Confirm failing tests before implementation.
- Call `app.disableHardwareAcceleration()` in `src/webapp/main.cjs` before
  readiness and window creation; preserve tray and close behavior.
- Run `node --test src/webapp/main.test.js` and inspect all results.

### Task 3: Review, verification, commit

- Review changed files and entry-point coverage independently.
- Run packaging-environment pytest, `npm --prefix src/webapp run lint`,
  `npm --prefix src/webapp test`, and `npm --prefix src/webapp run build`.
- Record exact verification and limitations, excluding private logs/paths.
- Stage only this workstream and commit with a detailed rationale, affected
  entry points, test results, and non-claims about installed acceptance.
- Do not push, merge, install, stop the running app, or run CUDA reproducers.
