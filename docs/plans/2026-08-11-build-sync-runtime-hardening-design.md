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
- Node version and module ABI;
- the stable, sorted physical `node_modules` closure as relative package path,
  package name, and exact version.

When state is absent, mismatched, forced, or `npm ls --depth=0` reports an
invalid direct dependency, the CLI removes the old state, runs `npm ci` with
the existing Electron mirror retry, validates the direct dependency tree, and
scans the resulting physical package closure before atomically writing the new
state. A matching identity still runs `npm ls` and then compares the complete
current closure with the saved one, so semver-compatible version drift and
missing or extra nested packages force a clean sync. Scoped and nested packages
are included; symbolic links are not followed, preventing traversal loops. Old
state without a closure and failed install, validation, or scanning attempts
cannot be reused. The Electron binary check remains after dependency sync. On
macOS, a frontend rebuild invalidates the native codesign stamp so native
modules are signed again.

Every persistent entrypoint invokes `scripts/sync-dependencies.cjs` with an
explicit `--webapp-root`. The two macOS launchers additionally pass their
frontend native-signature stamp through `--invalidate-stamp`; the CLI removes
that stamp only when it is about to mutate `node_modules`, and the existing
signing function runs after a successful sync. `VANTAGE_FORCE_FRONTEND_DEPS=1`
forces the same clean path without introducing a launcher-specific branch.

## Backend environment synchronization

A stdlib-only Python CLI owns the dedicated runtime venv lifecycle. The state
file `.vantage-backend-runtime-state.json` records:

- the joint hash of `requirements-core.txt` and the runtime overlay;
- the creating Python implementation/version and target platform;
- the exact bootstrap installer identity (`pip==25.3`);
- the normalized sorted `distribution==version` closure installed in the venv.

Reuse requires a matching state, an existing target interpreter, an identical
current distribution closure, a successful `pip check`, the required runtime
imports, and a clean OpenCV normalization check. A requirements change, forced
sync, failed validation, legacy SHA-only stamp, or extra/missing distribution
invalidates state before mutation and recreates the entire dedicated venv.
After install, OpenCV normalization and `pip check` must succeed before the
state is written atomically. Pip's download cache remains reusable, so the clean
environment does not imply repeated network downloads.

`RUN.bat`, `RUN.sh`, `RUN_DEV.sh`, and the release-installer builder all invoke
that one CLI with the project root, fixed venv, core requirements, overlay, and
OpenCV normalizer. None of those entrypoints writes its own dependency stamp or
runs an incremental requirements install. Before a rebuild the CLI atomically
renames only the exact `.venv-backend-runtime-gpu` sibling to a random
same-parent quarantine; it does not delete a validity marker while the old
canonical environment remains reachable.
The synchronizer must itself run outside that venv: the unresolved launcher
path, resolved interpreter target, and creating interpreter prefix are all
checked before any state invalidation or command execution, so a POSIX venv
Python symlink cannot make the process delete its own active environment.
Failed creation, installation, normalization, validation, or atomic replacement
therefore cannot leave a reusable state. On macOS, successful synchronization
is followed by the existing ad-hoc signing pass, keyed to the new environment
state rather than the retired requirements-only hash. A native-library signing
failure removes the signature stamp and aborts the launcher; it cannot be
recorded as successfully signed.

The complete venv lifecycle is serialized by a sibling
`.vantage-backend-runtime.lock`. POSIX uses `flock`; Windows locks one byte with
`msvcrt`, so process exit releases ownership and a residual lock file is not an
occupied lock. A bootstrap supervisor holds this lock for every official build,
verification, and development-server consumer. Direct build, verify, and
source-server entrypoints acquire it themselves unless the supervisor marker is
inherited. The synchronizer captures the old root's `lstat` identity before its
atomic rename, then revalidates identity, parent, and quarantine prefix. A root
or nested Windows reparse point, an identity race, or an unsafe inspection
retains the quarantine with a warning and never enters recursive deletion.
Rename failure leaves the canonical environment and state untouched; later
installation failure leaves the new canonical environment without valid state.

The packaged-runtime fingerprint includes the verified distribution closure.
Consequently, manually changing the venv cannot reuse an older PyInstaller
bundle even if source files and requirements text are unchanged. Packaging
validation also rejects a venv whose state is absent or inconsistent. The
fingerprint schema is version 2, and the environment sync CLI is explicitly
excluded from the shipped backend application as build-only code. There is no
environment-variable bypass for the fixed venv, state, or installed-closure
checks.

Reproducibility intentionally uses shared exact top-level requirement pins plus
a clean resolver run and a verified installed closure; it does not claim a
single cross-platform fully transitive hash lock. Changing the bootstrap pip pin
changes environment identity and forces a rebuild. An operator who can
simultaneously rewrite both the dedicated venv and its matching state file is
inside the local build-host trust boundary; this design detects ordinary drift,
not deliberate same-host state forgery.

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
