# Deterministic Build Sync and Runtime Hardening Design

## Status

Approved on 2026-08-11 when the user requested that every actionable item from
the daily audit be fixed completely. External provider credentials and model
entitlements remain operator-owned; this design fixes the application and build
paths without committing secrets or guessing an unauthorized model.

## Goals

- Make every Windows/macOS launcher and the release builder consume the same
  frontend dependency graph as GitHub Actions.
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
all persistent entrypoints. Its state includes:

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

The CLI holds one cross-process Node lock from before the first state or
lockfile read until after the final atomic state replacement. The same lease
therefore serializes state validation, native-signature-stamp invalidation,
`npm ci`, `npm ls`, physical closure scanning, and state publication across all
launchers. Exclusive creation records only a process id, random owner token,
and timestamp; an IPC child lease removes the lock when its parent exits or
crashes. A subsequent process quarantines a dead owner's residue before
continuing. Lock files are checked by physical identity and reject links,
non-regular files, and hard links. Waiting is bounded to 300 seconds by default
and fails closed with path-free diagnostics; transient lease and quarantine
files are ignored by Git.

`RUN.bat`, `RUN.sh`, `RUN_DEV.bat`, `RUN_DEV.sh`, and the release-installer
builder invoke `scripts/sync-dependencies.cjs` with an explicit
`--webapp-root`. `START_WEBAPP.bat` is only a compatibility alias that delegates
to `RUN_DEV.bat`; it has no independent install or launch branch. The two
macOS launchers additionally pass their
frontend native-signature stamp through `--invalidate-stamp`; the CLI removes
that stamp only when it is about to mutate `node_modules`, and the existing
signing function runs after a successful sync. `VANTAGE_FORCE_FRONTEND_DEPS=1`
forces the same clean path without introducing a launcher-specific branch.

## Backend environment synchronization

A stdlib-only Python CLI owns the dedicated runtime venv lifecycle. The state
file `.vantage-backend-runtime-state.json` records:

- the joint hash of `requirements-core.txt` and the runtime overlay;
- the creating Python implementation, full version, cache tag, `sys.platform`,
  operating-system name, and machine architecture;
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

`RUN.bat`, `RUN.sh`, `RUN_DEV.bat`, `RUN_DEV.sh`, and the release-installer
builder all invoke that one CLI with the project root, fixed venv, core
requirements, overlay, and OpenCV normalizer. `START_WEBAPP.bat` delegates to
`RUN_DEV.bat`. None of those entrypoints writes its own dependency stamp or runs
an incremental requirements install. Before a rebuild the CLI atomically
renames only the exact `.venv-backend-runtime-gpu` sibling to a random
same-parent quarantine; it does not delete a validity marker while the old
canonical environment remains reachable.
The synchronizer must itself run outside that venv: the unresolved launcher
path, resolved interpreter target, and creating interpreter prefix are all
checked before any state invalidation or command execution, so a POSIX venv
Python symlink cannot make the process delete its own active environment.
Failed creation, installation, normalization, validation, or atomic replacement
therefore cannot leave a reusable state. On macOS, successful synchronization
is followed by a shared stdlib-only signing CLI that holds the same lifecycle
lock. Its JSON stamp hashes the backend environment state and a stable closure
of every native library's venv-relative path, size, and SHA-256. A matching
stamp is reusable only after `codesign --verify --strict --verbose=2` succeeds
for every library. A state or byte change, forced signing, or failed cached
verification removes the stamp before ad-hoc signing, verifies every refreshed
signature, recomputes the post-signing closure, and atomically replaces the
stamp. Signing, verification, or stamp replacement failure leaves no valid
stamp and aborts the launcher.

The signer accepts only the fixed runtime, state, and stamp paths. It rejects
links, reparse points, hard links, containment escapes, and identity changes at
the runtime root, `lib` root, state, stamp, or native library. Extended
attributes are cleared only on individually validated native files. Cached and
new signing paths both verify a stable closure twice after signature checks,
then revalidate the state hash, file identities, stamp payload, and complete
native closure again after the atomic stamp replacement. A concurrent add,
delete, replacement, byte mutation, or link swap therefore removes the stamp
and aborts instead of certifying a mixed snapshot.

All mutating backend-signing commands operate on private same-filesystem copies.
On POSIX, the signer keeps validated parent-directory descriptors open and the
bounded child first changes directory through the inherited descriptor before
executing `xattr` or `codesign` with a relative basename. Cached and installed
verification use the same descriptor-bound path. Renaming an ancestor or
replacing the canonical path therefore cannot redirect a command or signature
stamp operation to a different tree; stamp read, write, replace, and cleanup
are likewise relative to the held runtime-root descriptor.

A second stdlib-only signer owns launcher-time frontend natives and the staged
PyInstaller backend bundle. Its profiles accept only their exact tracked roots.
Frontend candidates must have a Mach-O/fat header; the known
`esbuild/bin/esbuild` JavaScript wrapper is excluded explicitly, while an
unexpected non-Mach-O native candidate fails closed. The PyInstaller profile
preserves internal bundle symlinks, rejects escaping links, and signs each
resolved native entity once. Both profiles use private staging, stable closure
rescans, strict installed verification, and the same descriptor-bound command
execution. Only the frontend profile writes a reusable state stamp, and only
after a final closure and payload recheck.

All environment probes, pip commands, packaging workers, and codesign calls
have explicit timeouts and bounded fixed-size output capture. Timed-out process
groups/trees are terminated rather than leaving pipe-inheriting descendants
alive. Error summaries redact Bearer/Basic authorization, URL credentials,
common token forms, and known project, worker, and user paths before they can
reach persisted logs.

The macOS bootstrap-Python probe runs in its own shell process group with no
temporary output file; an early-exiting parent with live descendants is rejected
and the complete group is terminated. Electron's `afterPack` hook routes
`plutil`, `ditto`, `xattr`, and `codesign` through a stdlib bounded-command
bridge. Attribute cleanup walks with `lstat`, skips symlinks, rejects hard
links, and batches by both path count and argument bytes. The hook strictly
verifies the final copied application after attribute cleanup and deletes the
unverified output application on any failure.

The complete venv lifecycle is serialized by a sibling
`.vantage-backend-runtime.lock`. POSIX uses `flock(LOCK_SH/LOCK_EX)` so each
open file description retains its lease; Windows uses byte-range locks with 64
reader slots. Sync and signing take an exclusive lease, while build,
verification, packaging, and source-server consumers own shared leases
themselves.
Before opening or extending the sibling lock file, the lock implementation
uses no-follow open semantics where available and cross-checks `lstat`/`fstat`.
It rejects links, reparse points, non-regular files, hard links, and identity
races, so acquiring a lease cannot modify an external file through the lock
path.
The bootstrap launcher first acquires a shared lease, then starts an independent
bootstrap lease-owner. The owner acquires its own real shared lease, sends
READY, and waits for launcher GO (or launcher-death EOF) before it starts the
target-venv command; it keeps that lease until the command exits. The launcher's
lease overlaps this two-phase handshake, so terminating the launcher cannot
expose an already-started target to destructive synchronization. If it
terminates before the owner acquires its lease, the target has not started and
the owner waits for any intervening exclusive sync. The launcher readiness wait
is bounded and may stop an unready owner safely because the owner cannot start
the target before GO. POSIX passes only the two pipe descriptors with
`pass_fds`; Windows passes only the two explicitly listed pipe handles and does
not rely on inherited `LockFileEx` ownership. Both processes strip the legacy
`VANTAGE_BACKEND_RUNTIME_LOCK_HELD` marker and never treat environment text as
proof of ownership. The owner starts the target in an isolated process group;
if its target wait fails or the owner receives a handled interruption, it
terminates that process tree before releasing the lease. Process exit releases
the OS lease, so a residual lock file is not an occupied lock. The handoff
contract covers loss of the outer launcher; forcibly terminating the
lease-owner itself releases its OS lease, so any such administrative action
must also terminate the guarded target process tree. The synchronizer
captures the old root's `lstat` identity before its atomic rename, then
revalidates identity, parent, and quarantine prefix. A root or nested Windows
reparse point, an identity race, or an unsafe inspection retains the quarantine
with a warning and never enters recursive deletion.
Nested POSIX venv symlinks are unlinked as leaves without following their
targets; a POSIX symlink at the venv root is retained in quarantine and is
never recursively traversed. Before synchronization, the macOS launchers prefer
an executable existing runtime Python for the best-effort psutil cleanup, then
fall back to bootstrap Python, allowing an old development server to release
its shared lease.
Rename failure leaves the canonical environment and state untouched; later
installation failure leaves the new canonical environment without valid state.

The packaged-runtime fingerprint includes the verified distribution closure.
Consequently, manually changing the venv cannot reuse an older PyInstaller
bundle even if source files and requirements text are unchanged. Packaging
validation also rejects a venv whose state is absent or inconsistent. The
environment-state schema is version 2. The packaged-runtime fingerprint schema
is version 3 and includes the complete Python, platform, machine, and installed
distribution identities. Environment sync, lifecycle, signing, and background
launch helpers are explicitly excluded from the shipped backend application as
build-only code. There is no
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

CI uses GitHub's `macos-14` (arm64) and `macos-15-intel` (x64) runners. Both
architectures run the shared clean environment synchronizer, `pip check`, YuNet
prewarm, real native-library signing, cached-signature verification, and a
state-tamper refresh check. They also exercise the real POSIX shared/exclusive
lock semantics and synchronize, sign, and cache-verify the real frontend native
dependency closure, with the test dependency pin included in the cache key.
`RUN.sh` ad-hoc signs and strictly verifies every packaged backend native
binary; signing or verification failure aborts packaging. CI syntax-checks both
macOS launchers but does not notarize or publish a macOS release.

## Runtime hardening

- Screenshot capture constructs `mss.MSS()` directly; atomic multi-monitor
  behavior and the macOS fallback remain unchanged.
- The sedentary transition log is emitted only when an active session first
  crosses into confirmed absence. Continued absence is silent.
- Repeated location outcomes are logged on transition and then at most hourly,
  with a suppressed-repeat count. Coordinates remain absent from logs.
- Backend and Electron log messages replace known user-data/project prefixes
  with stable labels before persistence. Electron redaction scans URL-context
  events and all explicit-prefix candidates from the immutable original text,
  selects longest non-overlapping ranges, and applies replacements once. It
  handles encoded local file URLs and structured diagnostic fields while
  preserving genuine remote URLs and linear-time behavior. File basenames may
  remain for diagnostics; raw absolute user paths do not.
- Directory-size scans retain one `os.scandir()` iterator across bounded steps
  and preserve filesystem enumeration order; they never materialize or sort a
  whole directory. Processed-entry identities prevent double counting after a
  retry, and iterators close on completion, failure, path replacement, and
  shutdown. A completed result is cached for fifteen minutes; partial results
  keep `storage_scan_truncated=true`.

## Real YuNet smoke fixture

The repository commits Wikimedia's server-generated 120-pixel-wide thumbnail
of `File:WS Headshot.jpg` unchanged under CC0 1.0. Metadata records the original
and thumbnail URLs, author, license, retrieval date, dimensions, sizes, both
SHA-256 values, and EXIF status. No local crop, resize, re-encoding, metadata
stripping, or generative edit was applied; the downloaded thumbnail already has
no EXIF entries. The real bundled YuNet/OpenCV test requires exactly one legal
foreground box at or above the 1.0% threshold. Existing synthetic tests retain
exact boundary, malformed-output, largest-face, non-frontal, and UNKNOWN
semantics.

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
