# Focus Presence Regression Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore reliable, restart-safe focus-time tracking without bringing the removed heavyweight YOLO runtime back.

**Architecture:** Split raw YuNet presence from stricter camera-facing classification, carry tri-state observations through the monitor, and persist a narrowly bounded restart-recovery record under the runtime directory. Make the camera loop the sole physical-frame producer, complete Unicode media handling, and expose measurement status independently from focus duration.

**Tech Stack:** Python 3.11, OpenCV YuNet, FastAPI, React, pytest, Node test runner, Electron packaging.

---

### Task 1: Separate presence from camera-facing classification

**Files:**
- Modify: `src/services/person_detection.py`
- Modify: `src/manager/take_photo/take_a_photo.py`
- Test: `tests/test_person_detection.py`
- Test: `tests/test_take_photo.py`

**Step 1: Write the failing tests**

Add tests proving that a moderate-confidence, non-frontal YuNet face counts as
presence while the camera-facing API still rejects it. Make the fake detector
honor `setScoreThreshold` so the previous all-0.96 fixture cannot hide threshold
regressions. Update photo tests to require the presence API and tri-state
`None` for capture or detector failure.

**Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_person_detection.py tests/test_take_photo.py -q -p no:cacheprovider`

Expected: FAIL because the presence-specific API and tri-state behavior do not exist.

**Step 3: Write minimal implementation**

Add a separate presence threshold and raw-face detection path. Keep
`detect_camera_facing_faces()` and its geometry filter intact. Route periodic
photo presence through the raw presence count and return `None` for untrusted
capture/inference results.

**Step 4: Run tests to verify GREEN**

Run the same focused pytest command and expect all tests to pass.

### Task 2: Make focus state tri-state and restart-safe

**Files:**
- Modify: `src/manager/manager_main.py`
- Modify: `src/server.py`
- Test: `tests/test_sedentary_monitor.py`
- Test: `tests/test_server_startup_idempotence.py`

**Step 1: Write the failing tests**

Cover `present -> unknown -> present`, confirmed absence beyond the grace
period, short-restart recovery, stale/corrupt/future recovery-state rejection,
and runtime-directory injection from server startup.

**Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_sedentary_monitor.py tests/test_server_startup_idempotence.py -q -p no:cacheprovider`

Expected: FAIL because the monitor has no tri-state recorder or persistence.

**Step 3: Write minimal implementation**

Add observation-state recording and an atomic, versioned recovery file. Restore
only after a fresh positive observation inside the grace window. Preserve the
timer on unknown measurements and keep stale-heartbeat reporting separate.

**Step 4: Run tests to verify GREEN**

Run the same focused pytest command and expect all tests to pass.

### Task 3: Preserve media state and complete Unicode image support

**Files:**
- Modify: `src/manager/manager_main.py`
- Modify: `src/server.py`
- Test: `tests/test_sedentary_monitor.py`
- Test: `tests/test_latest_images_endpoint.py`

**Step 1: Write the failing tests**

Prove that a confirmed presence with failed photo storage does not replace the
last valid photo path, and that a valid image under a Unicode path is decoded
and passed to person validation.

**Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_sedentary_monitor.py tests/test_latest_images_endpoint.py -q -p no:cacheprovider`

Expected: FAIL on path overwrite and `cv2.imread` Unicode behavior.

**Step 3: Write minimal implementation**

Only replace media paths with non-empty successful outputs. Decode stored image
bytes through `numpy.fromfile` plus `cv2.imdecode`.

**Step 4: Run tests to verify GREEN**

Run the same focused pytest command and expect all tests to pass.

### Task 4: Fix warmup recovery and monitor frame ownership

**Files:**
- Modify: `src/server.py`
- Modify: `src/manager/take_photo/take_a_photo.py`
- Test: `tests/test_cross_platform_capture.py`
- Test: `tests/test_sedentary_monitor.py`

**Step 1: Write the failing tests**

Cover dark frames throughout warmup without reopen, reopen counting only after
warmup, first valid frame publication, and monitor use of a copied
`state.latest_frame` rather than concurrent physical-camera reads.

**Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_cross_platform_capture.py tests/test_sedentary_monitor.py -q -p no:cacheprovider`

Expected: FAIL because warmup dark frames currently reach the reopen threshold and monitor capture bypasses the published frame.

**Step 3: Write minimal implementation**

Ignore dark-frame streak accumulation until warmup completes. Add an optional
pre-captured frame to the photo/monitor path and pass a locked copy of the
published latest frame from `monitor_loop()`.

**Step 4: Run tests to verify GREEN**

Run the same focused pytest command and expect all tests to pass.

### Task 5: Report measurement status correctly in the dashboard

**Files:**
- Modify: `src/server.py`
- Modify: `src/webapp/src/components/Dashboard.jsx`
- Modify: `src/webapp/src/utils/displayCopy.js`
- Test: `tests/test_sedentary_monitor.py`
- Test: `src/webapp/src/components/Dashboard.test.js`
- Test: `src/webapp/src/utils/displayCopy.test.js`

**Step 1: Write the failing tests**

Add endpoint contracts for present, absent, unknown, and stale observations.
Add frontend tests proving unknown displays a paused/unavailable measurement,
not confirmed absence, while keeping the last valid duration visible.

**Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_sedentary_monitor.py -q -p no:cacheprovider`

Run: `npm --prefix src/webapp test -- src/webapp/src/components/Dashboard.test.js src/webapp/src/utils/displayCopy.test.js`

Expected: FAIL because observation status is not returned or rendered.

**Step 3: Write minimal implementation**

Return a stable `detection_status` field and duration snapshot. Render distinct
present, absent, and temporarily unavailable copy without discarding the last
known focus duration.

**Step 4: Run tests to verify GREEN**

Run both focused commands and expect all tests to pass.

### Task 6: Full regression and installed-runtime verification

**Files:**
- Modify only if a verification failure proves another in-scope regression.

**Step 1: Run source verification**

Run:

- `python -m pytest -q -p no:cacheprovider`
- `npm --prefix src/webapp test`
- `npm --prefix src/webapp run lint`
- `npm --prefix src/webapp run build`
- `git diff --check`

**Step 2: Validate packaging dependencies**

Run the repository packaging verifier with
`.venv-backend-runtime-gpu\\Scripts\\python.exe` and confirm the YuNet asset and
runtime dependencies are present.

**Step 3: Run the complete install flow**

Run `RUN.bat` from the repository root and let it finish naturally.

**Step 4: Verify the installed application**

Confirm installed build metadata matches the repair branch, the backend owns
`127.0.0.1:8000`, `/api/status` reports a valid camera frame, and
`/api/health/sedentary` reports a stable detection status with monotonically
increasing duration while the user remains present. Inspect only fresh logs for
reset, Unicode, warmup, and backend errors.
