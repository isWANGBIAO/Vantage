# Deterministic Build Sync and Runtime Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make local and remote builds consume the same verified dependency graphs, add real macOS/YuNet smoke coverage, and remove the runtime performance, deprecation, privacy, and repeated-log defects found in the 2026-08-11 audit.

**Architecture:** Use small dependency-free sync CLIs as the single source of truth for persistent frontend and backend environments. Frontend reuse is keyed by the lockfile plus Node/platform ABI; backend reuse is keyed by requirements, Python/platform identity, `pip check`, and the exact installed distribution closure, with a clean dedicated-venv rebuild on any mismatch. Runtime cleanups remain behavior-preserving and independently tested: resumable directory scans, transition-only state logs, hourly location-result throttling, path redaction, and direct `mss.MSS()` construction.

**Tech Stack:** Python 3.11/3.13, pytest, Node 24.18, npm, Electron 42.8, PowerShell, Batch, Bash, GitHub Actions macOS arm64/Intel runners, OpenCV 4.14 YuNet ONNX.

---

### Task 1: Synchronize frontend dependencies from the lockfile

**Files:**
- Create: `src/webapp/scripts/sync-dependencies.cjs`
- Create: `src/webapp/src/frontendDependencySync.test.js`
- Modify: `RUN.bat`
- Modify: `RUN.sh`
- Modify: `RUN_DEV.bat`
- Modify: `RUN_DEV.sh`
- Modify: `START_WEBAPP.bat`
- Modify: `scripts/build-release-installer.ps1`
- Modify: `tests/test_launcher_safety.py`
- Modify: `docs/plans/2026-08-11-build-sync-runtime-hardening-design.md`

**Step 1: Write failing Node and launcher tests**

Test that the desired state contains the lock SHA-256, Node version/module ABI,
platform, and architecture. Test a clean matching state skip, a stale lock
running `npm ci`, `npm ls --depth=0` invalidating an otherwise matching state,
exact installed-version drift plus missing/extra scoped and nested packages,
legacy state without a closure, failure leaving no stamp, and atomic stamp
creation only after validation.
Static launcher tests must require every persistent entrypoint to call the same
CLI and must forbid the old `node_modules`-existence shortcut.

**Step 2: Verify RED**

Run:

```powershell
npm --prefix src/webapp test -- --run
python -m pytest tests/test_launcher_safety.py -q
```

Expected: failures report the missing sync CLI and the four old existence-only
branches.

**Step 3: Implement the minimal sync CLI**

Export pure helpers plus a CLI. Use only Node built-ins. Write state under
`node_modules/.vantage-package-lock-state.json`. On mismatch or
`VANTAGE_FORCE_FRONTEND_DEPS=1`, delete the state first, run `npm ci`, retry once
with `VANTAGE_ELECTRON_MIRROR_FALLBACK` only when no explicit mirror exists,
run `npm ls --depth=0`, and atomically replace the state. On a valid fast path,
still run `npm ls --depth=0`, then compare a stable physical package closure of
relative path, name, and exact version; validation failure or any closure drift
forces a clean resync without following symbolic links.

Replace duplicated install branches with this CLI. Preserve the existing
Electron binary verification. In Bash launchers, dependency sync must remove
the macOS frontend codesign stamp before mutation and the existing signing
function must run after success.

**Step 4: Verify GREEN and the original reproduction**

```powershell
npm --prefix src/webapp test -- --run
python -m pytest tests/test_launcher_safety.py -q
npm --prefix src/webapp ls electron react react-dom --depth=0
```

Create a temporary stale state in a temporary copied webapp fixture and verify
the CLI replaces it; do not mutate the main checkout's `node_modules`.

**Step 5: Commit**

```powershell
git add RUN.bat RUN.sh RUN_DEV.sh scripts/build-release-installer.ps1 src/webapp/scripts/sync-dependencies.cjs src/webapp/src/frontendDependencySync.test.js tests/test_launcher_safety.py docs/plans/2026-08-11-build-sync-runtime-hardening-design.md
git commit -m "fix: synchronize persistent frontend dependencies" -m "Key frontend reuse to package-lock plus Node and platform ABI, validate npm's direct tree before stamping, preserve mirror retry and macOS re-signing, and remove the node_modules-exists shortcut from every persistent build entrypoint."
```

### Task 2: Rebuild and validate the dedicated backend environment

**Files:**
- Create: `src/core/backend_environment_state.py`
- Create: `src/core/backend_runtime_lock.py`
- Create: `src/scripts/sync_backend_runtime_environment.py`
- Create: `src/scripts/run_with_backend_runtime_lock.py`
- Create: `src/scripts/sign_macos_backend_runtime.py`
- Create: `src/scripts/sign_macos_artifacts.py`
- Create: `src/scripts/run_bounded_command.py`
- Create: `src/scripts/launch_locked_backend_background.py`
- Create: `src/utils/subprocess_safety.py`
- Create: `tests/test_sync_backend_runtime_environment.py`
- Create: `tests/test_backend_runtime_lock.py`
- Create: `tests/test_macos_cleanup_launcher.py`
- Create: `tests/test_sign_macos_backend_runtime.py`
- Create: `tests/test_sign_macos_artifacts.py`
- Create: `tests/test_run_bounded_command.py`
- Create: `tests/test_launch_locked_backend_background.py`
- Create: `tests/test_subprocess_safety.py`
- Modify: `RUN.bat`
- Modify: `RUN.sh`
- Modify: `RUN_DEV.bat`
- Modify: `RUN_DEV.sh`
- Modify: `START_WEBAPP.bat`
- Modify: `scripts/build-release-installer.ps1`
- Modify: `src/core/backend_runtime_packaging.py`
- Modify: `src/scripts/build_backend_runtime.py`
- Modify: `src/scripts/run_packaging_builds.py`
- Modify: `src/webapp/scripts/sign-mac-ad-hoc.cjs`
- Modify: `src/webapp/package.test.js`
- Modify: `src/utils/sensitive_data.py`
- Modify: `tests/test_packaging_builds_orchestrator.py`
- Modify: `tests/test_backend_runtime_packaging.py`
- Modify: `tests/test_launcher_safety.py`
- Modify: `docs/plans/2026-08-11-build-sync-runtime-hardening-design.md`

**Step 1: Write failing environment-state tests**

Cover canonical sorted `name==version` snapshots, atomic JSON state writes,
requirements/Python/platform mismatch, missing/extra distributions, failed
`pip check`, a legacy SHA-only stamp, forced sync, clean reuse, and failure
leaving no valid state. Require mismatch to delete and recreate the dedicated
venv rather than uninstalling a deny-list. Require all persistent launchers to
invoke the same helper and forbid direct stamp writes. Require every target-venv
consumer to own a real shared OS lease, never trust an inherited environment
marker, and keep blocking an exclusive synchronizer after its supervisor exits.

Add packaging tests that change only the distribution closure and observe a
different fingerprint. Bump the fingerprint schema and require packaging
validation to reject a missing or inconsistent environment state.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_sync_backend_runtime_environment.py tests/test_backend_runtime_packaging.py tests/test_launcher_safety.py -q
```

Expected: the state/helper APIs do not exist and the old launchers can still
stamp an incrementally polluted venv.

**Step 3: Implement clean rebuild semantics**

The stdlib-only helper computes the joint requirements hash, captures the
creating interpreter, platform, and exact `pip==25.3` bootstrap identity,
executes child-interpreter metadata probes, and validates `pip check` plus
required imports. When validation fails, atomically quarantine the dedicated
venv under the same parent, recreate it, install the overlay, run the existing
OpenCV normalizer, run `pip check`, capture the closure, and atomically write
`.vantage-backend-runtime-state.json`. Root or nested reparse points and
identity races retain quarantine rather than entering recursive deletion.

The launchers pass project root, venv, core requirements, overlay, normalizer,
and force mode to this helper. A sibling OS-released lifecycle lock covers the
entire synchronizer and every target-venv consumer. Official entrypoints use a
bootstrap supervisor during process creation; direct build, verify, packaging,
and source-server entrypoints each acquire a shared OS lease themselves.
Synchronization and signing take the exclusive lease. The legacy inherited
environment marker is cleared and never accepted as ownership proof. A helper
error aborts before packaging.

Add the verified distribution closure to
`build_backend_runtime_fingerprint()`. Packaging must validate that its current
interpreter matches the state file and closure before considering reuse.
Exclude the sync and macOS signing CLIs from the packaged application.

After macOS synchronization, invoke only the shared signing CLI. It holds the
lifecycle lock and keys its JSON stamp to the environment-state SHA plus the
stable relative-path, size, and SHA-256 closure of native libraries. Even a
matching stamp must pass strict `codesign` verification for every library. A
state/content change or failed verification invalidates the stamp before all
libraries are ad-hoc signed with timestamping disabled, verified again, and the
post-sign closure is atomically recorded. Any signing, verification, or atomic
replacement failure leaves no valid stamp. The launchers retain no independent
backend signing implementation.

Route launcher-time frontend natives and the staged PyInstaller backend bundle
through a second shared stdlib signer. It must use exact profile roots, private
staging copies, stable closure rescans, strict installed verification, and
descriptor-bound relative command paths. Frontend candidates must be real
Mach-O/fat binaries; exclude only the known esbuild JavaScript wrapper and fail
closed for unexpected non-Mach-O native candidates. Preserve PyInstaller's
internal bundle symlinks, reject escaping links, and sign each resolved native
entity once. Bind every stamp operation and failure cleanup to the already-open
validated root descriptor.

Replace the shell bootstrap probe's temporary output file and parent-only kill
with an isolated process group. Add a bounded-command bridge for Electron's
macOS `afterPack` hook, and route `plutil`, `ditto`, `xattr`, and `codesign`
through it. Clean attributes only on `lstat`-validated non-link, single-link
paths in bounded batches; strictly verify the final copied app, and remove the
output app on any failure.

This is a shared exact top-level-pin plus clean-resolver contract, not a single
all-platform transitive hash lock. Simultaneously forging both the dedicated
venv and its matching state remains inside the trusted local build-host
boundary.

The runtime fingerprint schema is version 3 and binds full Python identity,
cache tag, platform, operating system, machine architecture, and the verified
distribution closure. The signer rejects link/reparse and
hard-link/containment/identity races for the runtime, `lib`, state, stamp, and
native files. It clears attributes only on individually validated native files
and performs stable post-verification and post-stamp closure rescans. The lock
file itself uses no-follow identity validation and rejects link, reparse,
non-regular, and multi-link inputs before mutation. Child probes, pip
operations, packaging workers, and codesign calls use explicit timeouts,
fixed-size bounded output, process-tree termination, and credential plus
project/worker/local-path redaction.
`RUN_DEV.bat` uses the shared frontend/backend synchronizers and a detached
lifecycle supervisor; `START_WEBAPP.bat` delegates to it entirely.

**Step 4: Verify GREEN and migrate the real dirty environment**

```powershell
python -m pytest tests/test_sync_backend_runtime_environment.py tests/test_backend_runtime_packaging.py tests/test_backend_runtime_lock.py tests/test_sign_macos_backend_runtime.py tests/test_sign_macos_artifacts.py tests/test_run_bounded_command.py tests/test_packaging_builds_orchestrator.py tests/test_subprocess_safety.py tests/test_launch_locked_backend_background.py tests/test_launcher_safety.py tests/test_backend_requirements.py -q
python src/scripts/sync_backend_runtime_environment.py --project-root . --venv .venv-backend-runtime-gpu --core-requirements requirements-core.txt --requirements requirements-backend-runtime-gpu.txt --opencv-normalizer src/scripts/normalize_opencv_installation.py
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pip check
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pip list --format=json
```

Expected: the real old environment is rebuilt; Ultralytics, Torch,
TorchVision, ONNX Runtime GPU, and undeclared SciPy are absent; OpenCV contrib
is the only OpenCV distribution; a second helper invocation takes the validated
reuse path.

**Step 5: Commit**

```powershell
git add RUN.bat RUN.sh RUN_DEV.bat RUN_DEV.sh START_WEBAPP.bat scripts/build-release-installer.ps1 src/core/backend_environment_state.py src/core/backend_runtime_lock.py src/core/backend_runtime_packaging.py src/scripts/build_backend_runtime.py src/scripts/launch_locked_backend_background.py src/scripts/run_bounded_command.py src/scripts/run_packaging_builds.py src/scripts/run_with_backend_runtime_lock.py src/scripts/sign_macos_artifacts.py src/scripts/sign_macos_backend_runtime.py src/scripts/sync_backend_runtime_environment.py src/utils/subprocess_safety.py src/webapp/package.test.js src/webapp/scripts/sign-mac-ad-hoc.cjs tests/test_backend_runtime_lock.py tests/test_backend_runtime_packaging.py tests/test_launch_locked_backend_background.py tests/test_launcher_safety.py tests/test_macos_cleanup_launcher.py tests/test_packaging_builds_orchestrator.py tests/test_run_bounded_command.py tests/test_sign_macos_artifacts.py tests/test_sign_macos_backend_runtime.py tests/test_subprocess_safety.py tests/test_sync_backend_runtime_environment.py docs/plans/2026-08-11-build-sync-runtime-hardening-design.md
git commit -m "fix: rebuild unclean backend packaging environments" -m "Replace incremental stamp trust with a clean dedicated-venv rebuild on any requirements, Python, platform, pip-check, or installed-closure mismatch and include the verified distribution snapshot in packaged-runtime cache identity."
```

### Task 3: Add real macOS dependency smoke coverage

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_workflow.py`
- Modify: `README.md` if its workflow/platform wording needs alignment

**Step 1: Write the failing workflow contract**

Require a `macos-14` arm64 and `macos-15-intel` matrix. Require Python 3.13,
shared clean runtime synchronization, `pip check`, OpenCV/NumPy/YuNet
constructor probe, model prewarm, real native-library signing plus cached
verification/state-tamper refresh, real frontend dependency synchronization
plus native-signature cache verification, and `bash -n RUN.sh RUN_DEV.sh`.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_ci_workflow.py -q
```

Expected: no macOS job exists.

**Step 3: Add the job and verify GREEN**

Use official GitHub-hosted labels and `actions/setup-python@v5` pip caching
keyed by both runtime requirements files. Assert each runner's actual machine
architecture; run the shared environment, frontend synchronization, and both
signer CLIs; verify the frontend cache path; and make `RUN.sh` strictly sign and
verify each packaged backend native binary. Do not add signing secrets,
notarize, or publish artifacts.

Run the real POSIX shared/exclusive lock suite on both architectures and include
the CI requirements file in the cache key so the tested `pytest` pin cannot
drift behind a restored environment.

```powershell
python -m pytest tests/test_ci_workflow.py -q
python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8'))"
```

**Step 4: Commit**

```powershell
git add .github/workflows/ci.yml tests/test_ci_workflow.py README.md
git commit -m "ci: exercise macOS runtime dependencies" -m "Add arm64 and Intel macOS smoke jobs for the packaged Python requirements, OpenCV YuNet constructor and prewarm, pip consistency, and launcher syntax without changing the Windows release workflow."
```

### Task 4: Remove screenshot and repeated-state log defects

**Files:**
- Modify: `src/manager/screenshot/take_a_screenshot.py`
- Modify: `tests/test_screenshot_capture.py`
- Modify: `src/manager/manager_main.py`
- Modify: `tests/test_sedentary_monitor.py`
- Modify: `src/manager/get_location.py`
- Modify: `tests/test_get_location_save_image.py`

**Step 1: Write failing tests**

Require screenshot capture to construct `mss.MSS()` and make use of the
deprecated lowercase alias fail the test. Drive monitor capture across the
confirmed-absence boundary and another absent cycle, asserting exactly one
reset message. Drive repeated identical rejected location outcomes with an
injected monotonic clock, asserting transition-first logging, suppression, and
one hourly summary without coordinates.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_screenshot_capture.py tests/test_sedentary_monitor.py tests/test_get_location_save_image.py -q
```

**Step 3: Implement minimal behavior-preserving changes**

Use `mss.MSS()`. Delete the continued-absence reset branch while retaining the
transition log and grace countdown. Add a small thread-safe location outcome
rate limiter keyed by source/status/reason; accuracy changes must not defeat
suppression and latitude/longitude must never enter the message.

**Step 4: Verify GREEN and warning reproduction**

```powershell
python -m pytest tests/test_screenshot_capture.py tests/test_sedentary_monitor.py tests/test_get_location_save_image.py -q
python -W error::DeprecationWarning -c "import mss; from src.manager.screenshot.take_a_screenshot import take_and_save_screenshots; assert 'mss.mss' not in __import__('inspect').getsource(take_and_save_screenshots)"
```

**Step 5: Commit**

```powershell
git add src/manager/screenshot/take_a_screenshot.py src/manager/manager_main.py src/manager/get_location.py tests/test_screenshot_capture.py tests/test_sedentary_monitor.py tests/test_get_location_save_image.py
git commit -m "fix: silence recurring capture state warnings" -m "Use the supported MSS constructor, emit confirmed absence only on transition, and rate-limit unchanged location trust outcomes without weakening location policy or exposing coordinates."
```

### Task 5: Make storage scans resumable and cached

**Files:**
- Create: `src/services/directory_size_scanner.py`
- Create: `tests/test_directory_size_scanner.py`
- Modify: `src/server.py`
- Modify: `tests/test_storage_stats.py`

**Step 1: Write failing scanner tests**

Build a nested temporary tree and give each step a one-entry budget. Assert
that consecutive steps visit new entries rather than restarting, partial totals
increase monotonically, completion produces the exact size, completed results
perform no I/O before the fifteen-minute refresh deadline, refresh/path change
starts a new traversal, disappearing files are skipped, and all paths remain
inside the configured root without following symlinked directories.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_directory_size_scanner.py tests/test_storage_stats.py -q
```

**Step 3: Implement and wire the scanner**

Use a queue of pending directories plus accumulated totals and a visited set.
Keep one persistent `os.scandir()` iterator for the current directory and
preserve filesystem enumeration order; never materialize or sort a whole
directory. Check the time budget around iterator open, advance, and entry
processing. Retain processed-entry identities so retrying a failed root cannot
double-count, and close iterators on completion, failure, path replacement, and
shutdown. `update_storage_stats()` owns one scanner per current path, publishes
partial totals with `storage_scan_truncated=true`, and serves completed cached
totals until refresh. Legacy one-shot scanning keeps its bounded helper.

**Step 4: Verify GREEN**

```powershell
python -m pytest tests/test_directory_size_scanner.py tests/test_storage_stats.py tests/test_server_startup_idempotence.py -q
```

**Step 5: Commit**

```powershell
git add src/services/directory_size_scanner.py src/server.py tests/test_directory_size_scanner.py tests/test_storage_stats.py
git commit -m "perf: resume bounded storage scans" -m "Continue directory-size traversal across one-minute budget slices, cache completed exact results for fifteen minutes, and preserve the existing partial-result API marker without repeatedly rescanning the same prefix."
```

### Task 6: Redact persisted local paths

**Files:**
- Modify: `src/utils/sensitive_data.py`
- Modify: `src/scripts/run_server_background.py`
- Modify: `tests/test_sensitive_data.py`
- Modify: `tests/test_run_server_background.py`
- Modify: `src/webapp/src/utils/boundedLogger.cjs`
- Modify: `src/webapp/src/utils/boundedLogger.test.js`
- Modify: `src/webapp/main.cjs`
- Modify: `src/webapp/main.test.js`

**Step 1: Write failing Python and Node tests**

Require known user-home, runtime-data, project, and executable prefixes to be
replaced by stable labels in persisted log entries, including error stacks.
Keep basenames and non-path diagnostics intact. Verify both slash styles and
case-insensitive Windows prefixes. API keys must remain redacted.

**Step 2: Verify RED**

```powershell
python -m pytest tests/test_sensitive_data.py tests/test_run_server_background.py -q
npm --prefix src/webapp test -- --run
```

**Step 3: Implement bounded redacting streams/loggers**

Extend sensitive-text redaction with explicit prefix mappings; do not use a
broad regex that could alter URLs or traceback line numbers. Wrap Python
stdout/stderr after file-descriptor redirection and sanitize Electron entries
inside the bounded logger before file append or console mirroring. Main passes
only known local roots. Preserve stream `flush`, `fileno`, `encoding`, error
isolation, rotation, and recursion guards. Electron collects URL-context events
and every explicit-prefix candidate from the immutable original message,
selects the longest non-overlapping ranges, and applies replacements once. This
handles encoded local file URLs and structured diagnostic fields while
preserving genuine remote URLs and avoiding mutation-dependent or quadratic
rescanning leaks.

**Step 4: Verify GREEN**

```powershell
python -m pytest tests/test_sensitive_data.py tests/test_run_server_background.py -q
npm --prefix src/webapp test -- --run
```

**Step 5: Commit**

```powershell
git add src/utils/sensitive_data.py src/scripts/run_server_background.py tests/test_sensitive_data.py tests/test_run_server_background.py src/webapp/src/utils/boundedLogger.cjs src/webapp/src/utils/boundedLogger.test.js src/webapp/main.cjs src/webapp/main.test.js
git commit -m "fix: redact local paths from persisted logs" -m "Replace explicit user-data, project, and executable prefixes before backend and Electron logs are persisted while preserving basenames, diagnostics, log rotation, and existing secret redaction."
```

### Task 7: Add a real licensed YuNet positive smoke fixture

**Files:**
- Create: `tests/fixtures/yunet/foreground_face_cc0.jpg`
- Create: `tests/fixtures/yunet/LICENSE.md`
- Create: `tests/test_person_detection_real_model.py`
- Modify: `.gitattributes` only if binary handling requires it

**Step 1: Download and document the source**

Verify the Wikimedia Commons `File:WS Headshot.jpg` page declares CC0 1.0 and
record the original plus official thumbnail URLs, author, license, retrieval
date, dimensions, sizes, both SHA-256 values, and EXIF status. Commit the
server-generated 120-pixel-wide thumbnail unchanged; do not crop, resize,
re-encode, strip metadata locally, or use a private/generated image. The
downloaded thumbnail must contain no EXIF entries.

**Step 2: Write and verify the RED smoke test**

Use the real bundled YuNet model and the public fixture. Assert the fixture is
readable and `detect_foreground_presence_face_boxes()` returns exactly one
legal clipped box at or above the 1.0% threshold. Temporarily point the fixture
path at an empty image to verify the assertion fails for the intended reason,
then restore it.

**Step 3: Verify GREEN in both available environments**

```powershell
python -m pytest tests/test_person_detection_real_model.py tests/test_person_detection.py tests/test_person_detection_model_config.py -q
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_person_detection_real_model.py -q
```

If pytest is intentionally absent from the packaged venv, run the second probe
as a direct Python script importing the detector and printing only numeric box
data.

**Step 4: Commit**

```powershell
git add tests/fixtures/yunet/foreground_face_cc0.jpg tests/fixtures/yunet/LICENSE.md tests/test_person_detection_real_model.py .gitattributes
git commit -m "test: exercise YuNet with a CC0 face fixture" -m "Add a documented, EXIF-free Wikimedia-generated CC0 thumbnail unchanged and verify the real bundled YuNet model produces exactly one qualifying foreground box, complementing the synthetic boundary tests without committing private imagery."
```

### Task 8: Full verification and local provider recovery

**Files:**
- Modify only if a verification failure produces a separately tested fix.

**Step 1: Run focused integration suites**

```powershell
python -m pytest tests/test_sync_backend_runtime_environment.py tests/test_backend_runtime_packaging.py tests/test_backend_runtime_lock.py tests/test_sign_macos_backend_runtime.py tests/test_packaging_builds_orchestrator.py tests/test_subprocess_safety.py tests/test_launch_locked_backend_background.py tests/test_launcher_safety.py tests/test_backend_requirements.py tests/test_ci_workflow.py tests/test_screenshot_capture.py tests/test_sedentary_monitor.py tests/test_get_location_save_image.py tests/test_directory_size_scanner.py tests/test_storage_stats.py tests/test_sensitive_data.py tests/test_run_server_background.py tests/test_person_detection_real_model.py -q
```

**Step 2: Run full source validation**

```powershell
python -m pytest -q
npm --prefix src/webapp test -- --run
npm --prefix src/webapp audit --omit=dev
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
bash -n RUN.sh RUN_DEV.sh
```

Parse both PowerShell scripts with the PowerShell AST parser and run `git diff
--check`.

**Step 3: Verify clean dependency identities**

Run the backend sync helper twice. The first invocation may rebuild; the second
must reuse. Require `pip check` success, exact state/closure equality, one
OpenCV contrib distribution, no old YOLO/Torch/ONNX Runtime GPU/SciPy packages,
and a clean `npm ls` with Electron 42.8/React 19.2.8. Build the backend runtime
and confirm its manifest has YuNet, no YOLOX/forbidden package, and no undeclared
SciPy directory.

**Step 4: Recover the local provider only from advertised metadata**

Read local Vantage provider settings without printing secrets. Query configured
model-list endpoints. If an allowed model is advertised, update only the local
user setting and make one action-plan request. If the upstream is unreachable
or no permitted model exists, leave settings untouched and record the external
blocker; never commit or echo credentials.

**Step 5: Run the Windows install flow naturally**

```powershell
.\RUN.bat
```

After it exits successfully, verify installed build commit/version, Electron
dependency identity, backend runtime manifest/state, `/api/status`,
`/api/health/sedentary`, `/api/aqi`, 30-second CPU, fresh logs with no MSS
warning/repeated absence spam/raw local path, and one-photo-per-minute behavior.

**Step 6: Request final specification and quality review**

Review every item in
`docs/plans/2026-08-11-build-sync-runtime-hardening-design.md`, then dispatch an
independent code review over `origin/main..HEAD`. Resolve every Critical or
Important finding with its own RED/GREEN cycle and re-review.

**Step 7: Final documentation commit if verification changed docs only**

```powershell
git add docs/plans/2026-08-11-build-sync-runtime-hardening-design.md docs/plans/2026-08-11-build-sync-runtime-hardening.md
git commit -m "docs: record build hardening verification" -m "Record fresh source, dependency, packaged-runtime, installed-app, CPU, log, and provider verification evidence after the deterministic synchronization fixes."
```
