# Trusted Location Cross-Check and Fixed 1 Hz Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Cross-check browser AQI coordinates against a trusted backend sample, replace three background modes with one fixed prewarmed behavior, cap both live inference loops at 1 Hz, and release the verified result as Vantage 1.0.65.

**Architecture:** Preserve trusted location metadata through a new sample-returning backend adapter, then require browser and backend samples to pass freshness, timestamp-skew, and effective-distance checks before AQI uses the backend coordinate. Remove persisted performance-mode state across Python, Electron, and React; keep prewarmed mounting semantics and enforce a shared monotonic 1 Hz inference gate in the two server loops.

**Tech Stack:** Python 3.11/3.13, FastAPI, WinRT `winsdk`, OpenCV/YuNet, React 19, Electron, pytest, Node test runner, GitHub Actions.

---

### Task 1: Preserve backend location metadata and cross-check AQI samples

**Files:**
- Modify: `src/manager/get_location.py`
- Modify: `src/services/location_trust.py`
- Modify: `src/server.py`
- Modify: `tests/test_get_location_save_image.py`
- Modify: `tests/test_location_trust.py`
- Modify: `tests/test_aqi_location_trust.py`
- Modify: `tests/test_backend_path_resolution.py`

**Step 1: Write failing tests for the metadata-preserving adapter**

Add tests proving a new asynchronous adapter returns the accepted
`LocationSample` for both WinRT and explicit static configuration, returns
`None` for untrusted/missing metadata, and leaves `get_location()` and the
existing tuple-returning trusted-location wrappers compatible.

**Step 2: Run the adapter tests to verify RED**

```powershell
python -m pytest tests/test_get_location_save_image.py -q
```

Expected: FAIL because the adapter cannot yet return the trusted sample.

**Step 3: Implement the metadata-preserving adapter**

Refactor the existing asynchronous path so its internal/public sample entry
point returns `LocationSample | None` after resolver approval. Have the current
tuple API call that entry point and project only `(latitude, longitude)`. Do not
duplicate WinRT calls, static-override parsing, timeout handling, or trust
resolution.

**Step 4: Write failing cross-check tests**

Cover exact boundaries and failure behavior:

- browser-only sample is unavailable and never calls Open-Meteo;
- all four browser fields absent allows a trusted backend sample;
- any partial browser field set is unavailable even if backend is trusted;
- browser accuracy `1000` metres and age `120` seconds are accepted at the
  boundary; values above either boundary are rejected;
- absolute timestamp skew `30` seconds is accepted and greater values reject;
- effective distance `1000` metres is accepted and greater values reject;
- missing/untrusted backend sample rejects browser input;
- a matching trusted static or WinRT sample succeeds and its backend coordinate,
  never the browser coordinate, is sent upstream and returned;
- mismatch/untrusted paths return null coordinates and do not call upstream;
- stdout and application logging contain no raw coordinate values.

**Step 5: Run AQI tests to verify RED**

```powershell
python -m pytest tests/test_location_trust.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py -q
```

Expected: FAIL because the current endpoint trusts a browser sample alone and
falls back to backend coordinates after invalid browser metadata.

**Step 6: Implement cross-check validation**

Add a pure location-service helper that validates timestamp skew and calculates
haversine centre distance minus both samples' accuracy radii. Update `/api/aqi`
to distinguish fully absent browser metadata from any browser attempt. Validate
the browser sample with the existing AQI limits, fetch a fresh trusted backend
sample during the same request, compare them, and use only the backend sample on
success. Keep the endpoint signature, response keys, upstream timeout, access
logging disablement, and fail-closed privacy behavior unchanged.

**Step 7: Run targeted location tests to verify GREEN**

```powershell
python -m pytest tests/test_location_trust.py tests/test_get_location_save_image.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py -q
```

Expected: all tests pass.

**Step 8: Commit**

```powershell
git add src/manager/get_location.py src/services/location_trust.py src/server.py tests/test_get_location_save_image.py tests/test_location_trust.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py
git commit -m "fix: cross-check browser AQI location" -m "Require complete fresh browser metadata to agree in time and effective distance with a trusted backend sample. Preserve backend accuracy and timestamp metadata, use only the backend coordinate, and fail closed without exposing coordinates or calling Open-Meteo on mismatches."
```

### Task 2: Replace background modes with fixed 1 Hz inference

**Files:**
- Modify: `src/server.py`
- Modify: `tests/test_face_live_endpoint.py`

**Step 1: Write failing loop and eligibility tests**

Use controlled monotonic time, mocked inference, and a stoppable server state to
prove:

- consecutive YuNet inference starts are at least one second apart;
- consecutive live face analysis starts are at least one second apart;
- live face analysis remains eligible with no active viewer;
- YuNet remains eligible with no stream client when boxes are enabled;
- disabling boxes makes YuNet ineligible and clears cached boxes;
- old background-mode loaders and branches no longer exist.

Do not assert video-frame timing or change the camera capture loop.

**Step 2: Run the tests to verify RED**

```powershell
python -m pytest tests/test_face_live_endpoint.py -q
```

Expected: FAIL because both inference loops currently use 100 ms sleeps and
eligibility still depends on a background mode.

**Step 3: Implement the fixed runtime behavior**

Define a named one-second maximum-rate interval. Remove the background-mode
cache, sanitizer, loader, and conditional gating. Keep the live analysis loop
eligible while the server runs. Gate YuNet only on `show_person_box`; clear
`person_boxes` while disabled. In each loop, use `time.monotonic()` to delay an
inference start until one second after the previous start, without changing
camera acquisition, video generation, or focus/away timers.

**Step 4: Run focused runtime tests to verify GREEN**

```powershell
python -m pytest tests/test_face_live_endpoint.py tests/test_runtime_model_prewarm.py tests/test_server_startup_idempotence.py tests/test_take_photo.py tests/test_sedentary_monitor.py -q
```

Expected: all tests pass and existing prewarm/model-startup contracts remain
intact.

**Step 5: Commit**

```powershell
git add src/server.py tests/test_face_live_endpoint.py
git commit -m "perf: cap live face inference at one hertz" -m "Keep the single high-performance runtime continuously ready while limiting YuNet and live face analysis to one start per second. Remove background-mode gating without changing camera frame rate, focus tracking, or the away grace period."
```

### Task 3: Migrate settings to schema v2 and remove the mode UI

**Files:**
- Modify: `src/core/user_config.py`
- Modify: `tests/test_user_config.py`
- Modify: `src/webapp/src/utils/onboardingConfig.cjs`
- Modify: `src/webapp/src/utils/onboardingConfig.test.js`
- Modify: `src/webapp/src/utils/settingsState.js`
- Modify: `src/webapp/src/utils/settingsState.test.js`
- Modify: `src/webapp/src/components/Settings.jsx`
- Modify: `src/webapp/src/components/Settings.test.js`
- Modify: `src/webapp/src/utils/displayCopy.js`
- Modify: `src/webapp/src/App.jsx`
- Modify: `src/webapp/src/App.test.js`

**Step 1: Write failing Python migration tests**

Assert defaults and saved settings have `version == 2` and no
`background_mode`. Load version 1 fixtures containing every legacy mode and
prove the field is discarded while theme, language, launch-at-login,
action-plan generation, and provider settings are preserved. Saving the loaded
state must write schema v2 without the legacy key.

**Step 2: Verify Python RED**

```powershell
python -m pytest tests/test_user_config.py -q
```

Expected: FAIL because schema v1 and `background_mode` are still emitted.

**Step 3: Implement the Python migration**

Set `SETTINGS_VERSION = 2`, remove `background_mode` from defaults and sanitized
output, and remove the background-mode coercer. Keep all unrelated settings and
provider schema behavior unchanged.

**Step 4: Write failing Electron and React tests**

Assert that:

- Electron normalization reads v1 files but returns/writes v2 without
  `background_mode`;
- renderer defaults, normalization, browser storage, and save submissions never
  expose `backgroundMode`;
- Settings has no background-strategy control or three option values while the
  action-plan auto-generation row remains;
- App always preloads and mounts hidden background tabs after settings load,
  with no power-saver/prewarm branch;
- removed translation keys and labels are absent.

**Step 5: Verify frontend RED**

```powershell
npm --prefix src/webapp test -- --run src/utils/onboardingConfig.test.js src/utils/settingsState.test.js src/components/Settings.test.js src/App.test.js
```

Expected: FAIL because legacy mode state and UI are still present.

**Step 6: Implement schema v2 and fixed frontend preloading**

Update Electron and renderer normalizers to version 2 and omit the legacy key
on every output/save path. Remove mode form state, options, row, copy, and save
arguments. Simplify App preloading so chunks always preload after settings are
available and background tabs mount when preloading finishes, matching today's
prewarm path.

**Step 7: Verify GREEN**

```powershell
python -m pytest tests/test_user_config.py -q
npm --prefix src/webapp test -- --run
```

Expected: all Python config and frontend tests pass.

**Step 8: Commit**

```powershell
git add src/core/user_config.py tests/test_user_config.py src/webapp/src/utils/onboardingConfig.cjs src/webapp/src/utils/onboardingConfig.test.js src/webapp/src/utils/settingsState.js src/webapp/src/utils/settingsState.test.js src/webapp/src/components/Settings.jsx src/webapp/src/components/Settings.test.js src/webapp/src/utils/displayCopy.js src/webapp/src/App.jsx src/webapp/src/App.test.js
git commit -m "refactor: remove background performance modes" -m "Migrate settings to schema v2, discard the legacy background mode without disturbing other preferences, remove the mode selector and copy, and make the previous prewarm mounting behavior the single supported runtime policy."
```

### Task 4: Set version 1.0.65 and run release-candidate verification

**Files:**
- Modify: `src/webapp/package.json`
- Modify: `src/webapp/package-lock.json`
- Modify: public documentation only where it describes the removed modes or new
  cross-check behavior

**Step 1: Add or update contract tests before documentation/runtime changes**

Search tests and public docs for hardcoded mode or version contracts. Update
only assertions made obsolete by this design; do not weaken packaging, startup,
location privacy, or release-workflow checks.

**Step 2: Update the release version**

Set both root package-version entries to `1.0.65` using the repository's normal
package-version workflow. Do not hand-edit dependency versions or generated
build metadata.

**Step 3: Run targeted regression tests**

```powershell
python -m pytest tests/test_location_trust.py tests/test_get_location_save_image.py tests/test_aqi_location_trust.py tests/test_backend_path_resolution.py tests/test_face_live_endpoint.py tests/test_runtime_model_prewarm.py tests/test_server_startup_idempotence.py tests/test_sedentary_monitor.py tests/test_take_photo.py tests/test_backend_runtime_packaging.py tests/test_verify_backend_runtime.py -q
```

Expected: all targeted Python tests pass.

**Step 4: Run complete source verification**

```powershell
python -m pytest -q
npm --prefix src/webapp test -- --run
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
git diff --check
git status --short
```

Expected: all checks pass, and status contains only intended source,
documentation, and version changes.

**Step 5: Commit the release candidate**

```powershell
git add src/webapp/package.json src/webapp/package-lock.json README.md docs tests
git commit -m "chore: prepare Vantage 1.0.65" -m "Set the release version after trusted-location cross-checking, fixed one-hertz inference, schema migration, and public documentation have passed the complete Python and frontend verification suites."
```

Do not add unchanged or generated paths; narrow the `git add` list to the files
actually changed.

### Task 5: Verify the installed application and CPU release gate

**Files:**
- Inspect only unless verification reveals a source defect.

**Step 1: Run final specification and quality reviews**

Review `main...feature/location-trust` against both approved design documents.
Resolve every critical or important finding in a focused, detailed commit, then
repeat the affected tests and review.

**Step 2: Run the full Windows flow naturally**

```powershell
.\RUN.bat
```

Do not apply a short debug timeout or terminate it early. Confirm the installer
builds, installs, and launches.

**Step 3: Verify installed runtime contracts**

After the backend is stable for two minutes:

- verify `/api/status` and `/api/health/sedentary` are healthy;
- verify `/api/aqi` returns unavailable without trusted evidence and succeeds
  only through the backend-only or matched-browser paths;
- verify installed version `1.0.65` and the expected branch commit;
- verify runtime manifest/package contents and YuNet loading;
- search fresh logs for raw test/real coordinates and confirm none appear.

Use only synthetic coordinates in automated requests and do not save diagnostic
frames.

**Step 4: Measure CPU for the release gate**

Sample total-machine CPU for 30 seconds after the two-minute stabilization
period. Record the average and relevant Vantage process breakdown. Expected:
average total-machine CPU below 25%. At or above 25%, stop before push/tagging,
identify the remaining hot loop, add a failing regression test, and correct it.

**Step 5: Re-run changed tests after any correction**

If no correction was required, do not create an empty commit.

### Task 6: Push, merge, tag, and verify the GitHub release

**Files:**
- No source changes expected.

**Step 1: Push and open the ready PR**

```powershell
git push -u origin feature/location-trust
gh pr create --base main --head feature/location-trust --title "fix: trust location and cap live inference at 1 Hz" --body-file <reviewed-pr-body-file>
```

The PR body must summarize behavior, schema migration, privacy guarantees,
test counts, installed endpoints, and measured CPU; it must not include private
coordinates, local paths, or logs.

**Step 2: Wait for required checks and review**

Require successful Python 3.11, Python 3.13, frontend build, and CodeQL checks.
Address review findings with new commits and repeat relevant local verification.

**Step 3: Merge normally and synchronize local main**

```powershell
gh pr merge --merge --delete-branch
git -C D:\WANGBIAO\code\Vantage pull --ff-only origin main
```

Expected: PR merged with a merge commit and local `main` exactly matches
`origin/main`.

**Step 4: Tag and push 1.0.65**

```powershell
git -C D:\WANGBIAO\code\Vantage tag -a v1.0.65 -m "Vantage 1.0.65"
git -C D:\WANGBIAO\code\Vantage push origin v1.0.65
```

Tag only the verified merge commit and only after confirming its package version
is exactly `1.0.65`.

**Step 5: Verify release automation and assets**

Wait for the tag-triggered release workflow to succeed. Confirm the release
contains the installer, blockmap, and `SHA256SUMS.txt`, and verify the published
checksums against downloaded assets.

**Step 6: Re-run installed flow from merged main**

Run `RUN.bat` from synchronized `main` and let it finish naturally. Confirm the
installed app reports version `1.0.65`, the merge commit, healthy status and
sedentary endpoints, correct AQI trust behavior, and no coordinate logging.
