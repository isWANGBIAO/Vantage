# Trusted Location Cross-Check and Fixed 1 Hz Performance Implementation Plan

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

### Task 2A: Bound the real-time YuNet input after the installed CPU gate

The first installed 30-second gate averaged about 60% total-machine CPU. An
A/B run with green boxes disabled fell below 18%, and an isolated benchmark
showed that the 4K YuNet call consumed roughly five CPU seconds while a
640-pixel-long-edge input used well below one CPU second. The fixed 1 Hz policy
therefore needs a bounded inference input in addition to start-time pacing.

Add failing tests proving that the real-time foreground-box interface:

- resizes a 3840x2160 frame to 640x360 before YuNet inference;
- maps the selected box back to original-frame coordinates;
- preserves the normalized 0.5% foreground-area boundary and largest-face rule;
- keeps small inputs unchanged and invalid output unavailable; and
- does not change photo presence or strict historical analysis inputs.

Implement the resize only in
`detect_foreground_presence_face_boxes()`. Keep the confidence, model, identity
boundary, photo cadence, and historical analysis path unchanged. Re-run the
person-detection, live-loop, prewarm, photo, sedentary, packaging, and complete
test suites before repeating `RUN.bat` and the installed CPU gate.

```powershell
git add src/services/person_detection.py tests/test_person_detection.py docs/plans/2026-07-22-location-trust-fixed-performance-design.md docs/plans/2026-07-22-location-trust-fixed-performance.md
git commit -m "perf: bound realtime YuNet input size" -m "Preserve the foreground face contract while scaling only the live green-box inference input to a 640-pixel longest edge and mapping its selected box back to the original frame. Keep photo presence and strict historical analysis on their existing input paths."
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
Push-Location .\src\webapp
node --test .\src\utils\onboardingConfig.test.js .\src\utils\settingsState.test.js .\src\components\Settings.test.js .\src\App.test.js
Pop-Location
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

From the repository root, identify the process listening on backend port 8000
and wait two minutes for startup/model stabilization. During the same 30-second
window, collect 30 one-second total-machine CPU samples for the release gate and
retain normalized backend CPU plus memory as a diagnostic breakdown:

```powershell
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop |
  Select-Object -First 1
if (-not $listener) { throw "No backend listener found on port 8000." }

$backendPid = [int]$listener.OwningProcess
$logicalProcessors = [Environment]::ProcessorCount
if ($logicalProcessors -le 0) { throw "Logical processor count is unavailable." }

Start-Sleep -Seconds 120
$startProcess = Get-Process -Id $backendPid -ErrorAction Stop
$startCpuSeconds = [double]$startProcess.CPU
$sampleStart = Get-Date
$machineCounter = Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 30
$endProcess = Get-Process -Id $backendPid -ErrorAction Stop
$elapsedSeconds = ((Get-Date) - $sampleStart).TotalSeconds
$backendCpuDeltaSeconds = [double]$endProcess.CPU - $startCpuSeconds
$backendAverageCpuPercent = 100.0 * $backendCpuDeltaSeconds / ($elapsedSeconds * $logicalProcessors)
$machineCpuSamples = @($machineCounter.CounterSamples | ForEach-Object { [double]$_.CookedValue })
if ($machineCpuSamples.Count -ne 30) {
  throw "Release blocked: expected 30 total-machine CPU samples."
}
$machineAverageCpuPercent = [double](
  ($machineCpuSamples | Measure-Object -Average).Average
)

[pscustomobject]@{
  BackendPid = $backendPid
  LogicalProcessors = $logicalProcessors
  ElapsedSeconds = [math]::Round($elapsedSeconds, 2)
  MachineSampleCount = $machineCpuSamples.Count
  MachineAverageCpuPercent = [math]::Round($machineAverageCpuPercent, 2)
  BackendCpuDeltaSeconds = [math]::Round($backendCpuDeltaSeconds, 2)
  BackendAverageCpuPercent = [math]::Round($backendAverageCpuPercent, 2)
  BackendWorkingSetMiB = [math]::Round($endProcess.WorkingSet64 / 1MB, 2)
  BackendPrivateMemoryMiB = [math]::Round($endProcess.PrivateMemorySize64 / 1MB, 2)
} | Format-List

if ($machineAverageCpuPercent -ge 25.0) {
  throw "Release blocked: total-machine average CPU is not below 25%."
}
```

The listener must keep the same PID throughout the sample; `Get-Process` failing
therefore invalidates the measurement. The backend CPU and memory fields are
diagnostics and do not replace the total-machine gate. Record the output in the
private release check notes, not in the public repository. If the total-machine
average is at or above 25%, stop before pushing, merging, or tagging, identify
the load source, add a failing regression test when it is a Vantage defect, and
correct it.

**Step 5: Re-run changed tests after any correction**

If no correction was required, do not create an empty commit.

### Task 6: Push, merge, tag, and verify the GitHub release

**Files:**
- No source changes expected.

**Step 1: Push and open the ready PR**

```powershell
git push -u origin feature/location-trust
$pythonSummary = Read-Host "Paste the exact final pytest summary"
$frontendSummary = Read-Host "Paste the exact final frontend test summary"
$machineCpuSummary = Read-Host "Paste the measured total-machine average CPU percentage"
$backendResourceSummary = Read-Host "Paste the backend CPU and memory diagnostic summary"
$prBodyFile = Join-Path ([System.IO.Path]::GetTempPath()) "vantage-location-trust-pr.md"
@"
## Summary
- Cross-check browser AQI coordinates with a fresh trusted backend sample.
- Replace three background modes with one fixed prewarmed 1 Hz policy.
- Migrate settings to schema v2 and remove the legacy performance selector.
- Prepare Vantage 1.0.65.

## Verification
- Python: $pythonSummary
- Frontend: $frontendSummary
- Total-machine average CPU: $machineCpuSummary
- Backend CPU and memory diagnostics: $backendResourceSummary
- Installed `/api/status`, `/api/health/sedentary`, and AQI trust paths verified.
- Fresh logs checked for coordinate disclosure.
"@ | Set-Content -LiteralPath $prBodyFile -Encoding utf8
try {
  gh pr create --base main --head feature/location-trust --title "fix: trust location and cap live inference at 1 Hz" --body-file $prBodyFile
  if ($LASTEXITCODE -ne 0) { throw "PR creation failed." }
} finally {
  Remove-Item -LiteralPath $prBodyFile -ErrorAction SilentlyContinue
}
```

The PR body must summarize behavior, schema migration, privacy guarantees,
test counts, installed endpoints, and measured CPU; it must not include private
coordinates, local paths, or logs.

**Step 2: Wait for required checks and review**

Require successful Python 3.11, Python 3.13, frontend build, and CodeQL checks.
Address review findings with new commits and repeat relevant local verification.

**Step 3: Merge normally and synchronize local main**

Merge from the feature worktree:

```powershell
gh pr merge --merge
```

Then open a shell at the existing `main` worktree repository root and
synchronize it with relative Git commands:

```powershell
git fetch origin
git pull --ff-only origin main
```

Expected: PR merged with a merge commit and local `main` exactly matches
`origin/main`.

**Step 4: Tag and push 1.0.65**

```powershell
git tag -a v1.0.65 -m "Vantage 1.0.65"
git push origin v1.0.65
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

**Step 7: Remove the feature worktree and branches after release verification**

Only after the PR is merged, the release assets are verified, and the final
installation from `main` passes, run the following from the `main` worktree
repository root. Discover and remove the feature worktree first, then delete its
local branch:

```powershell
$featureWorktree = $null
$candidateWorktree = $null
foreach ($line in @(git worktree list --porcelain)) {
  if ($line.StartsWith('worktree ')) {
    $candidateWorktree = $line.Substring('worktree '.Length)
  } elseif ($line -eq 'branch refs/heads/feature/location-trust') {
    $featureWorktree = $candidateWorktree
  }
}
if (-not $featureWorktree) {
  throw "feature/location-trust worktree was not found."
}
git worktree remove -- $featureWorktree
if ($LASTEXITCODE -ne 0) { throw "Feature worktree removal failed." }
git branch -d feature/location-trust
if ($LASTEXITCODE -ne 0) { throw "Local feature branch deletion failed." }
```

Confirm GitHub still reports the PR as merged, then delete the remote branch as
a separate cleanup operation:

```powershell
$prState = gh pr view feature/location-trust --json state,mergedAt | ConvertFrom-Json
if ($prState.state -ne 'MERGED' -or -not $prState.mergedAt) {
  throw "Remote branch cleanup blocked: PR merge is not confirmed."
}
git push origin --delete feature/location-trust
```
