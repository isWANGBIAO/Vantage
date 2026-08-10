# YuNet and Dependency Stability Design

## Status

Approved on 2026-08-10. This design narrows the YuNet-only foreground
presence rule from the design approved on 2026-07-15 and integrates the two
open dependency update groups into one verified release.

## Goals

- Stop a fixed, empty workstation scene from creating a green face box or a
  presence photo.
- Preserve one-hertz sampling, immediate capture of the first qualifying frame
  in a natural minute, and the two-minute confirmed-absence grace period.
- Keep downward and side-facing foreground faces eligible for presence.
- Update the frontend and Python dependency groups without leaving CI contracts
  inconsistent with the tracked dependency versions.
- Produce and verify a synchronized source, release, and installed version.

## Foreground presence rule

YuNet presence continues to use confidence `0.50` and does not call the strict
camera-facing landmark rule. The normalized, clipped face-box area threshold is
raised from `0.005` to `0.01` (1.0% of the frame). Only the largest qualifying
face is returned.

The change is supported by numeric-only local evidence:

- known empty-scene false detections occupied approximately 0.50%-0.65% of the
  frame;
- previously measured background faces occupied at most approximately 0.116%;
- the foreground workstation user's previously measured minimum was
  approximately 2.76%.

The resulting threshold leaves margin below the observed foreground minimum
while rejecting all observed empty-scene detections. Private photos and image
paths are not test fixtures and must not be committed. Tests express the
boundary using synthetic YuNet rows: a box below 1.0% is absent, a box exactly
at 1.0% is present, and a moderate-confidence non-frontal face above the new
threshold remains present.

No identity recognition, center ROI, temporal multi-frame confirmation,
calibration, brightness heuristic, or new setting is introduced. These would
either reduce portability or conflict with the requirement to capture a person
who appears for only one sampled second.

## Dependency and CI integration

The frontend dependency group is updated together with its runtime contract.
Electron `42.8.0` remains paired with Node `24.18.0`; the package manifest,
lockfile, README/runtime documentation, and `tests/test_ci_workflow.py` must
agree. This fixes the deterministic Python CI failure in the existing frontend
Dependabot PR.

Python dependencies use one exact shared core rather than repeating divergent
pins in the development, CI, and packaged-runtime files. A new
`requirements-core.txt` owns every package used by all three environments,
including OpenCV `4.14.0.94`, the Python-version-qualified NumPy 2.x pins, and
the compatible Pydantic/Pydantic Core pair. `requirements.txt`,
`requirements-ci.txt`, and `requirements-backend-runtime-gpu.txt` each include
that file with `-r` and contain only environment-specific additions. Every
environment uses the single `opencv-contrib-python==4.14.0.94` distribution.
MediaPipe already requires the contrib distribution, and OpenCV's four Python
wheel families share the same `cv2` namespace and must not coexist. The official
PyPI release supplies Windows, macOS arm64/x64, and manylinux wheels, so one
cross-platform distribution is both resolvable and packaging-compatible.

This is a single source of truth for shared packages, not an unpinned install.
Exact versions retain reproducible CI and releases, while the small overlay
files keep research-only, test-only, and packager-only dependencies out of the
installed application. Runtime dependency stamps in `RUN.bat`, `RUN.sh`,
`RUN_DEV.sh`, and `scripts/build-release-installer.ps1`, packaged-runtime source
fingerprints, and GitHub Actions cache keys include both the overlay and its
shared core so a core-only change cannot reuse stale artifacts. The same
combined hash also invalidates the macOS native-library codesign stamp, because
a core-only update can replace native Python binaries. The standalone
`src/scripts/install_requirements.py` entrypoint passes the composed
`requirements.txt` to pip with `-r` in one operation, leaving include and marker
semantics to pip instead of treating include directives as package names. Its
result is file-scoped: success returns no failures, while a nonzero pip result
reports the requirements file path and makes the CLI exit with status 1.

The development overlay declares PyTorch's CUDA 13.0 wheel index so its exact
`torch==2.13.0+cu130` pin is discoverable. It also uses the jointly resolvable
`ipykernel==6.29.5`, `mpmath==1.3.0`, and `webcolors==25.10.0` pins. These are
verified as a complete Python 3.11 Windows requirements graph with pip's real
resolver in dry-run and ignore-installed mode; no large wheel is installed by
that check.

The packaged `runtime-manifest.json` verifies that the YuNet resources are
present and YOLOX is absent; it does not record package versions. OpenCV and
NumPy versions are verified independently by importing them from each target
interpreter or from the installed runtime.

Dependabot declared 16 Python dependency updates. Fifteen compatible updates
are accepted; the standalone `pydantic_core` update is rejected and the shared
core instead pins the pair required by `pydantic==2.13.4`:
`pydantic_core==2.46.4`. Separately, the pre-existing unmarked SciPy 1.18 pin is
corrected to SciPy `1.17.1` for Python 3.11 and `1.18.0` for Python 3.12 and
newer. That compatibility repair is not counted as a Dependabot update.

The Python 3.13 job was not deadlocked: its log shows that
`winsdk==1.0.0b10` built successfully from source for about 18 minutes. CI
continues to cache pip downloads and built wheels, now keyed by both the shared
core and CI overlay. A dependency update can cause a legitimate first-run cache
miss, while unchanged follow-up runs reuse the built wheel. Dependency and
platform coverage are not reduced.

## Tests and release

Verification covers:

- the 1.0% foreground boundary, largest-face selection, invalid YuNet output,
  non-frontal presence, one-hertz scheduling, photo deduplication, and the
  two-minute absence/recovery contracts;
- the known empty-scene images through a local numeric-only probe, without
  copying or committing those images;
- Electron/Node/package/lockfile/workflow consistency;
- Python 3.11 and 3.13 CI, frontend tests/build, CodeQL, and YuNet model loading
  in development, CI, and packaged-runtime environments under the same shared
  OpenCV 4.14 and NumPy contract;
- launcher contract tests plus `bash -n RUN.sh RUN_DEV.sh`, proving every
  dependency and macOS codesign stamp follows the combined core-and-overlay
  hash;
- the standalone requirements installer success/file-failure contract,
  including one composed `pip install -r` invocation, a successful zero-error
  CLI path, and an explicit failed-requirements-file `SystemExit(1)` path;
- a real Python 3.11 Windows root resolver dry-run proving the composed
  development graph resolves and its plan contains only
  `opencv-contrib-python`, with no second OpenCV distribution;
- the full Windows `RUN.bat` flow, installed version, commit metadata, health
  endpoints, the runtime manifest's YuNet/no-YOLOX resource contract, and
  independently queried installed OpenCV and NumPy versions.

The release version is `1.0.67`. The dependency branches are superseded or
closed after the integrated PR passes all required checks. The final merge,
annotated tag, release assets, checksums, and installed application must all
refer to the same merged source.
