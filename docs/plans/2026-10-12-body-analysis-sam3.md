# Body Analysis with Optional Local SAM3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Put dark-circle history, leg-hair, and scalp reports under one Body Analysis page, with local incremental SAM3 analysis and optional dependencies that do not enlarge the main installer.

**Architecture:** Vantage owns settings, startup scheduling, job status, and restricted report delivery. A small, sanitized standalone Python runner owns GPU inference in an optional per-user environment. The React page renders JSON and generated images; it never runs report HTML or touches arbitrary source paths.

**Tech Stack:** FastAPI/Python, Electron/React, PyInstaller resources, Node tests, pytest.

---

## Task 1: JSON settings and path validation

**Files:**
- Modify: `src/core/user_config.py`, `src/backend/settings.py`, `src/backend/api_contracts.py`, `src/services/automation_catalog.py`
- Test: `tests/test_user_config.py`, `tests/test_settings_automation_endpoint.py`, `tests/test_automation_catalog.py`

1. Write failing tests: round-trip `body_analysis_enabled`, `body_analysis_leg_dir`, `body_analysis_scalp_dir`, and `body_analysis_model_dir`; reject non-directory, repository-root, and overlapping output paths; preserve other settings when updating one field. Never assert a personal absolute path in a tracked fixture.
2. Run targeted pytest and confirm each failure is missing behavior, not an import error.
3. Add defaults (`false` and empty strings), sanitized path fields, API schema, and strict update validation. Resolve/validate paths at use time too, because directories can move after saving.
4. Run the same tests; inspect the serialized settings JSON under a temporary test root.
5. Commit only these files with a detailed message.

## Task 2: Sanitized standalone runner and report contract

**Files:**
- Create: `src/scripts/body_analysis_sam3.py`
- Test: `tests/test_body_analysis_runner.py`
- Reference only, never stage wholesale: `scripts/leg_hair/analyze_sam3.py`, `scripts/leg_hair/analyze_leg_hair.py`

1. Write failing tests for pure input discovery, EXIF capture date, per-photo record schema, no-detection=`null`, rejected scalp candidate excluded from aggregate trends, report manifest validation, and an output path that must be newly created under a caller-owned staging root.
2. Run targeted pytest and confirm red. Test images are synthetic fixtures only.
3. Extract only necessary local SAM3 inference and image/report helpers. Import Torch/Transformers lazily inside the runner; no API-key reads, provider calls, hard-coded private paths, automatic downloads, or recursive deletion. Accept explicit CLI arguments for the two source directories, checkpoint directory, output staging directory, and JSON progress destination. Emit structured JSON records and generated masks/overlays.
4. Run targeted pytest and a synthetic no-model contract check. Scan tracked runner for user paths, credentials, and network image requests.
5. Commit the sanitized runner and tests separately from the original untracked prototypes.

## Task 3: Optional environment detection and explicit installation

**Files:**
- Create: `src/services/body_analysis_environment.py`
- Modify: `src/core/backend_runtime_packaging.py`
- Test: `tests/test_body_analysis_environment.py`, `tests/test_backend_runtime_packaging.py`

1. Write failing tests for missing Python/model/dependencies, positive capability probe, explicit install request, independent per-user venv target, cancellation/error reporting, and no source image access during installation.
2. Confirm red with targeted pytest.
3. Locate a usable CPython on this computer or request one; never use the frozen backend as a Python interpreter. Install pinned optional packages only after the user clicks Install, in a separate environment under the configured user-data area. Do not download gated model weights; report that the selected local checkpoint is missing. Include the runner `.py` as a required packaged resource while continuing to exclude Torch/Transformers from the frozen backend. Keep the backend import tree lightweight.
4. Run targeted tests and inspect the packaging resource manifest. Any real package installation is a separate local acceptance step, not part of unit tests.
5. Commit environment/packaging changes.

## Task 4: Startup job and restricted report API

**Files:**
- Create: `src/services/body_analysis_jobs.py`, `src/backend/body_analysis.py`
- Modify: `src/backend/application.py`, `src/server.py`, and a non-repo user-data path helper in `src/core/config.py` if needed
- Test: `tests/test_body_analysis_jobs.py`, `tests/test_body_analysis_endpoint.py`, `tests/test_server_startup_idempotence.py`

1. Write failing tests for startup non-blocking single-flight, source fingerprint reuse, changed-image rerun, missing dependency status, retry, subprocess failure preserving the old report, atomic publication, bounded/redacted progress, and shutdown cancellation.
2. Write failing API tests for status/report/setup/install/retry, allowed generated image access, traversal and symlink rejection, and no raw source-path exposure. Run targeted pytest to see red.
3. Implement one lifespan-owned service. Fingerprint permitted images plus runner/checkpoint version. Run the runner with explicit argv (never shell), bounded concurrency, and child-process cleanup. Store manifests and report assets under user data, not the repository. Serve only whitelisted generated assets below the current published report root.
4. Run targeted tests; manually inspect that a failure never advances the successful fingerprint or deletes the last good report.
5. Commit service/API changes.

## Task 5: Body Analysis navigation, settings, and report UI

**Files:**
- Create: `src/webapp/src/components/BodyAnalysis.jsx`, `src/webapp/src/components/BodyAnalysis.test.js`
- Modify: `src/webapp/src/App.jsx`, `src/webapp/src/App.test.js`, `src/webapp/src/utils/displayCopy.js`, `src/webapp/src/utils/displayCopy.test.js`, `src/webapp/src/utils/settingsState.js`, `src/webapp/src/utils/settingsState.test.js`
- Modify narrow folder picker: `src/webapp/main.cjs`, `src/webapp/preload.cjs`, `src/webapp/src/utils/platformAdapter.js` and their tests

1. Write failing tests: new parent navigation with Dark Circles/Leg Hair/Scalp, old `#face-history` compatibility, FaceHistory mounted only while selected, folder selection saved to JSON, missing optional environment displayed without auto-install, explicit install click, report masks/quality flags, no trend for rejected scalp metrics, last successful report retained during refresh/failure.
2. Run targeted Node tests and confirm red.
3. Implement the smallest React container and narrow `openDirectory` IPC. Use existing backend request utilities. Render structured JSON and generated same-origin images; keep the current CSP unchanged and never embed generated HTML. Do not expose absolute photo paths in display errors.
4. Run targeted Node tests, then `npm --prefix src/webapp run lint`, `npm --prefix src/webapp test`, and `npm --prefix src/webapp run build`.
5. Commit UI/IPC changes.

## Task 6: Local setup, integrated verification, and handoff

**Files:**
- Modify docs only if behavior differs from the design; keep actual local paths solely in user-data JSON.

1. Recheck `git status` and staged scope. Run `python -m pytest -q`, frontend lint/test/build, and `npm --prefix src/webapp run never-stop:test`; Never Stop must remain unaffected.
2. Seed this computer's confirmed existing leg/scalp/model directories into local settings JSON through the validated API/UI. Preserve the original research scripts as untracked files until the user asks for cleanup.
3. If an optional environment is already available, use it. Otherwise exercise the explicit install/setup flow, wait for completion, and verify no model weights or images are copied into the repository or installer. Do not silently install into machine-wide Python.
4. Run an actual local startup analysis. Verify source count, missing detections, per-photo masks, rejected scalp metrics, and that the report is complete before publishing. Verify a second unchanged start reuses the report. Avoid unsupported trend claims.
5. Build/install via `RUN.bat` if a real installed-app acceptance is in scope; let it finish naturally. Check installed UI, V icon, package size, and optional environment separately. Report any step not performed rather than claiming full delivery.

## Commit and privacy rules

Commits must have detailed explanations and stage only intended tracked files.
Never `git add scripts/leg_hair` wholesale. Never commit photographs, reports,
model weights, local configuration, secrets, private prompts, or machine paths.
