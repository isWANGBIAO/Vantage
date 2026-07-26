# 1Hz Presence Photo Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect foreground presence with YuNet once per second and save the first qualifying full-resolution frame in each natural minute, while keeping source, GitHub `main`, the release, and the installed application on the same final commit.

**Architecture:** Reuse the existing realtime YuNet loop as the only 1Hz inference path. Submit qualifying original frames to a daemon single-consumer save queue so location and JPEG/disk latency cannot block inference. Keep persistence behind one shared, thread-safe natural-minute gate so the queue and the existing 60-second monitor cannot save duplicate presence photos. Treat the person-box setting as presentation-only: inference and minute capture continue when the overlay is hidden.

**Tech Stack:** Python 3, FastAPI, OpenCV/YuNet, pytest, Electron/Vite, GitHub Actions, electron-builder.

---

### Task 1: Add a shared natural-minute photo gate

**Files:**
- Modify: `src/manager/take_photo/take_a_photo.py`
- Test: `tests/test_take_photo.py`

**Step 1: Write the failing tests**

Add focused tests for a fresh `PresencePhotoMinuteGate`:

- two qualifying saves in the same natural minute produce one file and one GPS write;
- the first qualifying save in the next minute is accepted;
- a storage failure does not claim the minute, so the next attempt can retry;
- the original full-resolution frame is passed to `save_image_with_gps`;
- location lookup is evaluated only for an accepted save;
- concurrent same-minute calls result in exactly one save.

Also add a `take_photo()` regression proving that its existing detected-person return contract is unchanged when the shared gate suppresses a duplicate.

**Step 2: Run the tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_take_photo.py -q
```

Expected: FAIL because the natural-minute gate and shared save function do not exist.

**Step 3: Implement the smallest passing unit**

In `take_a_photo.py`:

- add `PresencePhotoMinuteGate`, keyed by normalized photo root plus `YYYYMMDDHHMM`;
- protect eligibility, persistence, and claiming with one lock;
- claim only after `save_image_with_gps` succeeds;
- add `save_presence_photo_once_per_minute(...)`, accepting an optional capture time and lazy location provider;
- retain second-resolution filenames and the existing year/month/day/hour directory layout;
- route `take_photo()` through the module-level shared gate without changing `True`/`False`/`None` presence semantics.

Do not scan old photos and do not persist the gate across restarts; the process-local limit is sufficient and avoids per-second filesystem scans.

**Step 4: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_take_photo.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add src/manager/take_photo/take_a_photo.py tests/test_take_photo.py
git commit -m "feat: gate presence photos to one per minute" -m "Add a shared thread-safe natural-minute capture gate used by the existing photo path. Preserve the full-resolution frame and retry after failed writes while keeping the established presence-state contract."
```

### Task 2: Capture from the always-on 1Hz YuNet loop

**Files:**
- Modify: `src/server.py`
- Modify: `tests/test_face_live_endpoint.py`
- Test: `tests/test_take_photo.py`
- Test: `tests/test_sedentary_monitor.py`

**Step 1: Write the failing tests**

Add loop-level regressions proving:

- YuNet still runs at 1Hz when `show_person_box` is false;
- hidden overlays leave `state.person_boxes` empty but still invoke the minute saver;
- a qualifying foreground face saves the original frame immediately and updates `state.paths["photo"]`;
- no qualifying face does not save;
- a stale retained camera frame does not save again in a later minute;
- a blocked location or disk save does not delay later 1Hz inference starts;
- a permanently blocked save holds at most one active plus two queued original frames, and a rejected minute leaves no pending claim;
- detector/model failure neither saves nor publishes a box;
- turning the overlay off clears the visible boxes immediately without disabling inference;
- inference start times remain at least one second apart.

Update any old test whose expected behavior incorrectly says that hiding the box stops YuNet.

**Step 2: Run the tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_take_photo.py tests/test_face_live_endpoint.py tests/test_sedentary_monitor.py -q
```

Expected: FAIL because the loop is currently gated by `show_person_box` and does not save photos.

**Step 3: Implement the smallest passing integration**

In `server.py`:

- remove the overlay toggle from the inference-run condition;
- copy the current original camera frame once per 1Hz cycle;
- accept the frame for persistence only while its published timestamp remains fresh under the existing monitor-frame TTL contract;
- call `detect_foreground_presence_face_boxes(...)` once;
- when a qualifying foreground box exists, submit the original frame without blocking to a daemon single-consumer save queue;
- let the worker call the shared minute saver with lazy `get_location`, deduplicate pending/successful minutes, and release failed minutes for retry;
- bound the queue to two waiting frames, use non-blocking submission with pending rollback on backpressure, and provide deterministic worker cleanup for tests;
- update `state.paths["photo"]` from the success callback only after a successful save;
- publish boxes only when `show_person_box` is true, otherwise retain an empty display list;
- on frame/model errors, do not claim a minute and keep visible boxes empty;
- on location/storage errors, do not claim a minute or replace the photo path, but preserve the successfully detected visible box and retry on the next fresh sample;
- leave the video-stream cadence, monitor cadence, two-minute grace, stale-frame handling, and strict historical face analysis unchanged.

**Step 4: Run focused regression tests**

Run:

```powershell
python -m pytest tests/test_take_photo.py tests/test_face_live_endpoint.py tests/test_sedentary_monitor.py tests/test_person_detection.py tests/test_renderer_camera_frame.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add src/server.py tests/test_face_live_endpoint.py tests/test_take_photo.py tests/test_sedentary_monitor.py
git commit -m "feat: save first 1Hz presence frame each minute" -m "Keep the realtime YuNet loop active independently of overlay visibility. Save the first qualifying foreground frame in each natural minute and expose the new path to the existing historical processing cycle."
```

### Task 3: Prepare version 1.0.66 and release documentation

**Files:**
- Modify: `src/webapp/package.json`
- Modify: `src/webapp/package-lock.json`
- Modify: `README.md`
- Modify: `.github/workflows/release.yml`
- Test: `tests/test_ci_workflow.py`

**Step 1: Add or update version contract coverage**

Ensure the release tests verify that package metadata is internally consistent and that documented/tag examples use `v1.0.66`.

**Step 2: Run the contract test to verify the old version fails**

Run:

```powershell
python -m pytest tests/test_ci_workflow.py -q
```

Expected: FAIL after the new `1.0.66` expectation is added.

**Step 3: Bump release metadata**

Set Electron package and lock metadata to `1.0.66`, and update current release examples to `v1.0.66`. Do not create the tag before the PR is merged.

**Step 4: Run release-contract tests**

Run:

```powershell
python -m pytest tests/test_ci_workflow.py -q
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add src/webapp/package.json src/webapp/package-lock.json README.md .github/workflows/release.yml tests/test_ci_workflow.py
git commit -m "release: prepare Vantage 1.0.66" -m "Align Electron metadata, release workflow examples, documentation, and version-contract tests for the one-hertz presence-photo release."
```

### Task 4: Review and full source verification

**Files:**
- Review all changes since `014b3cf9d9a6483d4681737b9d71eec8f2f552f5`

**Step 1: Run specification review**

Confirm every approved requirement is represented in code and tests, especially overlay independence, one inference path, one natural-minute save, full-resolution persistence, retry behavior, and unchanged presence/focus semantics.

**Step 2: Run code-quality review**

Inspect concurrency, lock scope, exception handling, privacy/logging, test isolation, API compatibility, and release metadata.

**Step 3: Run the complete verification matrix**

```powershell
python -m pytest -q
npm --prefix src/webapp test -- --run
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

Also rerun the focused camera, presence, sedentary, packaging, and runtime-validation test modules.

**Step 4: Verify repository hygiene**

Confirm no photos, logs, private prompts, machine paths, credentials, generated runtime data, or untracked build artifacts are staged.

### Task 5: Publish, merge, release, and synchronize the installation

**Files:**
- No additional source changes unless review or CI finds a defect

**Step 1: Push and create a ready PR**

Push `feature/one-hertz-presence-photo`, create a detailed ready PR targeting `main`, and include the test evidence and performance/storage impact.

**Step 2: Wait for required CI**

Require the Python matrices, frontend build/tests, and CodeQL to pass. Fix failures on the branch and re-run review before merging.

**Step 3: Merge and synchronize local `main`**

Use a normal merge. Fetch and fast-forward the local repository's `main` to the exact GitHub merge commit, then verify local and remote SHAs match.

**Step 4: Tag and verify the GitHub release**

Create and push annotated tag `v1.0.66` on the merge commit. Wait for the release workflow, then verify installer, blockmap, `SHA256SUMS.txt`, and asset hashes.

**Step 5: Build and install from merged `main`**

Run `RUN.bat` from the synchronized local `main` and let it finish naturally. Do not stop it on a short timeout.

**Step 6: Verify the installed source of truth**

After two stable minutes, verify:

- source `main`, `origin/main`, tag `v1.0.66`, release target, packaged `build-info.json`, and installed `app.asar` all identify the same merge commit;
- installed version is `1.0.66`;
- `/api/status`, `/api/health/sedentary`, camera streaming, and one-per-minute photo behavior are healthy;
- hiding green boxes does not stop background capture;
- 30-second average whole-machine CPU remains below the existing 25% release gate;
- fresh installed logs contain no coordinates, recursion, or new critical errors.

If any identity differs, the release is not complete: repair the drift and repeat installation verification.
