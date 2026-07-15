# YuNet-Only Foreground Presence Design

## Status

Approved on 2026-07-15. This design supersedes the dual YuNet/YOLOX presence
design in:

- `2026-07-14-focus-presence-regression-design.md`
- `2026-07-14-focus-presence-regression.md`

The accumulated focus/away state machine, stale-frame protection, and the
two-minute absence grace period remain in scope and must not be reverted with
the YOLOX work.

## Goal

Use YuNet alone to distinguish the foreground workstation user from small
background faces. Presence must accept a detectable foreground face regardless
of whether it passes the stricter camera-facing geometry check, while failures
to capture or classify a trustworthy frame remain unknown rather than absence.

## Foreground face selection

- Presence inference uses YuNet at confidence `0.50`.
- `PRESENCE_MIN_FACE_AREA_RATIO` is fixed at `0.005` (0.5% of the frame).
- Each YuNet face rectangle is clipped to the frame before its normalized area
  is calculated.
- Rows with too few fields, non-finite values, or non-positive clipped width or
  height are invalid model output. Invalid model output makes presence
  inference unavailable; it must not be converted into confirmed absence.
- Of the valid faces at or above the area threshold, only the largest is the
  foreground presence face. No qualifying face means confirmed absence when
  capture and inference otherwise succeeded.
- Presence selection does not call `is_roughly_frontal_face()` or apply any
  landmark-orientation constraint.

The live green overlay and focus presence timer consume the same selected
foreground face. The overlay therefore draws at most one box and cannot show a
background face that the timer ignores.

## Historical camera-facing analysis

Historical camera-facing analysis keeps its existing, independent semantics:

- YuNet confidence remains `0.75`;
- the existing five-landmark roughly-frontal geometry filter remains required;
- broadening live presence must not broaden historical camera-facing counts.

## Presence states and timing

- A qualifying foreground face means present, including detectable downward or
  side-facing faces that fail the camera-facing geometry check.
- A successful frame and YuNet inference with no qualifying face means absent.
  The existing two-minute absence grace period continues to preserve focus
  through short gaps and clears focus only after continuous confirmed absence.
- Camera failure, unusable or stale frames, YuNet load failure, and invalid
  model output mean unknown. Unknown freezes trusted timing and must not start
  or advance confirmed-away time.
- The public HTTP response schema does not change.

## YOLOX removal

The implementation removes the YOLOX detector and all of its supporting
surface area:

- preprocessing, postprocessing, detector caching, and model prewarm code;
- the YOLOX ONNX model, its license, and its model documentation;
- packaged-runtime resources and verification requirements;
- the `VANTAGE_PERSON_PRESENCE_MODEL_PATH` environment override.

YuNet remains bundled, prewarmed, and configurable through its existing model
override. Host-side cleanup must continue to remove unsupported model overrides
before launching the packaged backend.

## Acceptance evidence

Current numeric-only camera sampling measured the foreground user's face at
2.76%-3.84% of the frame and background faces at 0.026%-0.116%. These values
leave margin around the fixed 0.5% threshold and are not persisted as personal
calibration data.

Tests must demonstrate that:

- a large non-frontal YuNet face at confidence `0.55` is present;
- a small high-confidence background face is absent and has no overlay;
- foreground and background faces together select only the largest qualifying
  foreground face;
- multiple qualifying faces select only the largest;
- malformed or non-finite output becomes unknown;
- strict camera-facing analysis still rejects non-frontal faces;
- camera/frame/model failures and the existing two-minute absence/recovery
  behavior retain their current contracts;
- source and packaged runtimes contain YuNet but no YOLOX model, configuration,
  prewarm, or verification requirement.

## Explicit boundaries

This design does not perform face identity recognition and does not add a
region of interest, calibration flow, dynamic threshold, or user setting. A
different person who approaches the camera and becomes the largest face above
the threshold can still be classified as the foreground user. A fully hidden
face or the back of a head cannot be recognized by YuNet; the two-minute grace
period is the intended mitigation for that limitation.
