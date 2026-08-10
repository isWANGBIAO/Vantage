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

The Python dependency group is incorporated only after YuNet tests and the
numeric empty-scene probe pass under OpenCV `4.14.0.94`. The Python 3.13 job was
not deadlocked: its log shows that `winsdk==1.0.0b10` built successfully from
source for about 18 minutes. CI already enables pip caching keyed by the CI
requirements file; this dependency update caused a legitimate first-run cache
miss, while unchanged follow-up runs can reuse the built wheel. No redundant
workflow change and no reduction in dependency or platform coverage is needed.

## Tests and release

Verification covers:

- the 1.0% foreground boundary, largest-face selection, invalid YuNet output,
  non-frontal presence, one-hertz scheduling, photo deduplication, and the
  two-minute absence/recovery contracts;
- the known empty-scene images through a local numeric-only probe, without
  copying or committing those images;
- Electron/Node/package/lockfile/workflow consistency;
- Python 3.11 and 3.13 CI, frontend tests/build, CodeQL, backend runtime
  packaging, and YuNet model loading under the updated OpenCV package;
- the full Windows `RUN.bat` flow, installed version, commit metadata, health
  endpoints, and runtime manifest.

The release version is `1.0.67`. The dependency branches are superseded or
closed after the integrated PR passes all required checks. The final merge,
annotated tag, release assets, checksums, and installed application must all
refer to the same merged source.
