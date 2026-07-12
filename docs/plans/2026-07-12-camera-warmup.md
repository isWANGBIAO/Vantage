# Camera Warmup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a two-second camera warmup after startup and reconnect so automatic exposure and white balance settle before new frames reach the UI.

**Architecture:** Add small pure helper functions in `src/server.py` for calculating the warmup deadline and deciding whether a frame may be published. Integrate those helpers into `camera_loop()` while preserving existing blank-frame recovery and the last valid frame during reconnects.

**Tech Stack:** Python, OpenCV, pytest, FastAPI, Electron packaging.

---

### Task 1: Define warmup behavior with tests

**Files:**
- Modify: `tests/test_cross_platform_capture.py`
- Modify: `src/server.py`

1. Add tests proving the warmup lasts two seconds, rejects publication before its deadline, and permits publication at or after the deadline.
2. Run the focused tests and confirm they fail because the helpers do not yet exist.
3. Add the minimal constants and pure helpers.
4. Run the focused tests and confirm they pass.

### Task 2: Integrate warmup into camera capture

**Files:**
- Modify: `src/server.py`
- Modify: `tests/test_cross_platform_capture.py`

1. Add a source-level regression assertion that `camera_loop()` starts a new warmup after every successful open and gates `state.latest_frame` publication.
2. Run the test and confirm it fails against the current loop.
3. Set a new monotonic deadline after camera initialization and only publish nonblank frames once the deadline has elapsed.
4. Keep the previous valid frame untouched while warming up.
5. Run camera and renderer regression tests.

### Task 3: Package and validate

**Files:**
- Generated build/version files as required by `RUN.bat`

1. Run the relevant Python tests.
2. Run the frontend check.
3. Commit the source changes.
4. Run `RUN.bat` from the repository root and let it finish.
5. Verify `/api/status` and `/api/stream` report a nonblank frame after warmup.
6. Push `main` and confirm the local and remote commit IDs match.
