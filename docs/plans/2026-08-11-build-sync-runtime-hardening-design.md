# Deterministic Build Sync and Runtime Hardening Design

## Status

Approved on 2026-08-11 when the user requested that every actionable item from
the daily audit be fixed completely. External provider credentials and model
entitlements remain operator-owned; this design fixes the application and build
paths without committing secrets or guessing an unauthorized model.

## Goals

- Make local `RUN.bat`, macOS launchers, and the release builder consume the
  same frontend dependency graph as GitHub Actions.
- Guarantee that the dedicated packaged-backend environment is clean,
  dependency-consistent, and reproducible before it can be stamped or cached.
- Add real macOS arm64 and Intel dependency smoke coverage.
- Remove the current screenshot API deprecation and recurring presence/location
  log noise.
- Replace repeated full-prefix storage walks with a resumable cached scan that
  eventually reaches an exact result without rescanning the same prefix every
  minute.
- Add a legally reusable real YuNet positive fixture so model loading and a
  qualifying foreground detection are both exercised.
- Preserve YuNet-only one-hertz presence, one-photo-per-natural-minute,
  two-minute absence grace, AQI fail-closed behavior, and all HTTP contracts.

## Root causes

The frontend launch paths use the existence of `node_modules` as proof that it
matches `package-lock.json`. This is false after any lockfile update. GitHub
Actions uses `npm ci`, while a persistent local checkout silently keeps older
Electron and React installations.

The backend launch paths hash the requirements inputs but update an existing
venv with `pip install -r`. Pip installs and upgrades requested packages; it
does not remove packages deleted from the requirements graph. The current venv
therefore retains the removed YOLO/Torch stack and an undeclared SciPy even
though its requirements stamp matches. The stamp is written without `pip
check`, and the packaged-runtime fingerprint does not include the installed
distribution closure.

Storage statistics restart `os.walk` from the same root every 60 seconds. When
the fixed three-second or 20,000-entry budget is exhausted, every cycle repeats
the same prefix rather than continuing. Presence and location code also prints
unchanged terminal states each sampling cycle. Screenshot capture uses the
deprecated lowercase `mss.mss()` compatibility alias.

## Considered approaches

1. **Always rebuild everything.** Running `npm ci` and recreating the Python
   venv on every launch is simple and correct, but adds substantial startup
   latency when nothing changed.
2. **Validated state with clean rebuild on mismatch (selected).** Record the
   frontend lock/Node ABI and backend requirements/Python/distribution closure.
   Fast validation permits reuse; any mismatch invalidates the state before
   work begins and performs a deterministic clean sync.
3. **Incrementally prune known old packages.** This is fast but fragile: every
   future removed dependency needs another deny-list entry, and shared native
   namespaces such as `cv2` make partial uninstalls unsafe.

For storage, a longer fixed sleep would reduce I/O but retain permanently
partial values. A resumable scanner is selected because each bounded step makes
forward progress, publishes a clearly marked lower bound until complete, then
serves an exact cached value until its refresh deadline.

## Frontend dependency synchronization

A dependency-free Node CLI under `src/webapp/scripts/` owns frontend sync for
all four persistent entrypoints. Its state includes:

- SHA-256 of `package-lock.json`;
- operating system and architecture;
- Node version and module ABI.

When state is absent, mismatched, forced, or `npm ls --depth=0` reports an
invalid direct dependency, the CLI removes the old state, runs `npm ci` with
the existing Electron mirror retry, validates the direct dependency tree, and
atomically writes the new state. A failed install or validation leaves no state
to be reused. The Electron binary check remains after dependency sync. On
macOS, a frontend rebuild invalidates the native codesign stamp so native
modules are signed again.

## Backend environment synchronization

A stdlib-only Python CLI owns the dedicated runtime venv lifecycle. The state
file records:

- the joint hash of `requirements-core.txt` and the runtime overlay;
- the creating Python implementation/version and target platform;
- the normalized sorted `distribution==version` closure installed in the venv.

Reuse requires a matching state, an existing target interpreter, an identical
current distribution closure, a successful `pip check`, the required runtime
imports, and a clean OpenCV normalization check. A requirements change, forced
sync, failed validation, legacy SHA-only stamp, or extra/missing distribution
invalidates state before mutation and recreates the entire dedicated venv.
After install, OpenCV normalization and `pip check` must succeed before the
state is written atomically. Pip's download cache remains reusable, so the clean
environment does not imply repeated network downloads.

The packaged-runtime fingerprint includes the verified distribution closure.
Consequently, manually changing the venv cannot reuse an older PyInstaller
bundle even if source files and requirements text are unchanged. Packaging
validation also rejects a venv whose state is absent or inconsistent.

## macOS CI

CI adds a small matrix using GitHub's current standard labels `macos-14`
(arm64) and `macos-15-intel` (x64). Each job installs the packaged-runtime
requirements in a fresh venv, runs `pip check`, imports OpenCV/NumPy, confirms
`FaceDetectorYN_create`, prewarms YuNet, and syntax-checks `RUN.sh` and
`RUN_DEV.sh`. It does not attempt notarization or publish a macOS release.

## Runtime hardening

- Screenshot capture constructs `mss.MSS()` directly; atomic multi-monitor
  behavior and the macOS fallback remain unchanged.
- The sedentary transition log is emitted only when an active session first
  crosses into confirmed absence. Continued absence is silent.
- Repeated location outcomes are logged on transition and then at most hourly,
  with a suppressed-repeat count. Coordinates remain absent from logs.
- Backend and Electron log messages replace known user-data/project prefixes
  with stable labels before persistence. File basenames may remain for
  diagnostics; raw absolute user paths do not.
- Directory-size scans retain traversal state across bounded steps. A completed
  result is cached for fifteen minutes; path changes create a new scan. Partial
  results keep `storage_scan_truncated=true`.

## Real YuNet smoke fixture

The repository adds a small, cropped test image derived from Wikimedia Commons
`File:WS Headshot.jpg`, published under CC0 1.0. The fixture metadata records
the source page, original author, license, retrieval date, and any crop/resize.
The test uses the real bundled YuNet ONNX model and OpenCV implementation. It
asserts at least one legal foreground box above the 1% threshold, while the
existing synthetic tests continue to own exact boundary, malformed-output,
largest-face, non-frontal, and UNKNOWN semantics.

## Provider recovery boundary

The implementation does not hard-code a replacement for the locally configured
SJTU model and never copies API keys into the repository or logs. Final runtime
verification queries provider model metadata without printing credentials. If
the provider advertises an allowed model, only the user's local Vantage setting
may be updated and then verified with one action-plan request. If no permitted
model or reachable upstream is available, the application remains truthfully
unavailable and reports the specific connectivity/entitlement cause.

## Verification and rollout

TDD covers each state transition and failure path before implementation. The
focused suites are followed by full Python tests, frontend tests, production
dependency audit, lint, build, shell syntax checks, PowerShell parsing, and
clean resolver checks. A temporary deliberately dirty backend venv proves that
an extra package causes a clean rebuild and cannot receive a valid state.

`RUN.bat` is executed only after source validation and is allowed to finish
naturally. The installed package must match the tested commit, report healthy
status/sedentary endpoints, contain YuNet and no YOLOX/forbidden distribution,
use the locked frontend versions, and stay below the existing CPU target. No
push, PR, merge, tag, or release is performed without the user's integration
choice after the verified branch is complete.
