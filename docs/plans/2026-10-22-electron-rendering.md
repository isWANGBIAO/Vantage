# Electron Rendering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore smooth desktop scrolling without enabling webpage WebGL or changing the backend OpenCL policy.

**Architecture:** Electron uses its normal compositor rather than forcing software rendering. The main BrowserWindow disables page WebGL explicitly. Startup logs expose the actual feature status for installation verification.

**Tech Stack:** Electron, React, Node test runner, existing Windows build/install flow.

---

### Task 1: Regression contract

Modify `src/webapp/main.test.js`: execute the real startup boundary with an
Electron app double that records `disableHardwareAcceleration` calls; expect no
calls across supported platforms/packaging modes. Assert main-window
`webPreferences` includes `webgl: false` while preserving isolation and disabling
Node integration. Run `node --test src/webapp/main.test.js`; observe expected
failures before production changes.

### Task 2: Minimal runtime correction

Modify `src/webapp/main.cjs`: remove unconditional software rendering, add
`webgl: false`, and log `app.getGPUFeatureStatus()` after readiness/GPU updates.
Do not modify Python policy or saved settings. Re-run the focused tests, then
`npm --prefix src/webapp run check` and production protocol/UI smoke checks.
Run `.venv-backend-runtime-gpu/Scripts/python.exe -m pytest -q tests/test_cpu_runtime_policy.py`.
Review the diff independently and commit with root cause, retained protections,
tests and acceptance boundaries in the commit message.

### Task 3: Package and local acceptance

Back up/hash settings and providers outside the repository. Run `RUN.bat` to its
natural completion. Confirm installed build metadata, backend listener and GPU
composition log; compare configuration hashes. Ask the user to compare scrolling
in the installed window with Chrome. Do not report historical driver coexistence
as resolved merely because the UI is smooth. Do not push remote changes without
authorization.

### Release prerequisite discovered during verification

The fresh-configuration backend smoke exposed a pre-existing optional-model
boundary: `face_live_loop` tried to start external face analysis without model
configuration, while captured-photo analysis already skips that state. Add the
same `configuration_status()['ready']` gate to
`src/backend/camera.py:should_run_face_live_analysis`. First add tests in
`tests/test_face_live_endpoint.py` proving that unconfigured models neither run
nor initialize the runtime; keep loop timing tests independent of machine paths.
Retain all packaging log blockers. Run the focused camera, packaging verifier and
CPU-policy tests, independent review, then repeat the full build/install flow.
This does not install optional dependencies or change user settings.
