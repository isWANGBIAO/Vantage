# Focus Presence Regression Implementation Plan

## Goal

Restore body-aware, restart-safe focus tracking; add trusted away timing; pause
both timers through unobserved gaps; recover quickly when the camera becomes
available; and show durations in minute, hour, and day units.

## Architecture

- OpenCV YuNet remains responsible for face and camera-facing classification.
- A bundled OpenCV Zoo YOLOX int8 model supplies body-aware person presence.
- Presence is positive when either detector succeeds positively, negative only
  when both detectors succeed negatively, and unknown otherwise.
- The monitor owns accumulated trusted focus and away segments rather than
  deriving duration from wall-clock session starts.
- Camera frames carry monotonic publication timestamps and expire after five
  seconds for monitor use.
- FastAPI exposes additive away-timer fields; React selects and formats the
  active trusted timer.
- Packaged smoke verification runs real inference through both camera models.

## Task 1: Restore body-aware presence

**Files**

- `src/services/person_detection.py`
- `src/models/object_detection_yolox_2022nov_int8bq.onnx`
- `src/models/LICENSE.object_detection_yolox.txt`
- `src/core/backend_runtime_packaging.py`
- person-detection and packaging tests

**Acceptance criteria**

- YuNet face or YOLOX person is sufficient for presence.
- Absence requires two successful negative detectors.
- Detector failures produce unknown unless the other detector is positive.
- Invalid or non-finite model output cannot become a full-frame person box.
- The model and license are present in source and packaged runtime resources.

## Task 2: Track trusted focus and away duration

**Files**

- `src/manager/manager_main.py`
- `src/server.py`
- `tests/test_sedentary_monitor.py`

**Acceptance criteria**

- Present runs focus; absent runs away immediately; unknown pauses both.
- Unknown, capture latency, and stale-heartbeat gaps are never counted later.
- Exactly 120 trusted away seconds clears only the old focus session.
- Focus and away values remain monotonic inside their active episode.
- Version 2 state is atomic, version 1 migrates, restart downtime is excluded,
  and only a fresh matching trusted observation restores the candidate.
- The API retains existing fields and adds `away_duration_seconds` and
  `active_timer`.

## Task 3: Reject stale camera frames and retry quickly

**Files**

- `src/server.py`
- camera, renderer, monitor, and startup tests

**Acceptance criteria**

- Frame and monotonic publication timestamp update and clear atomically.
- Missing, invalid, future, or older-than-five-second frames become unknown.
- Present and absent cycles use the configured normal interval.
- Missing, stale, unknown, and failed cycles retry after two seconds.
- Renderer liveness uses monotonic time and preserves camera ownership rules.

## Task 4: Verify packaged camera inference

**Files**

- `src/server.py`
- `src/scripts/verify_backend_runtime.py`
- runtime-prewarm and verifier tests

**Acceptance criteria**

- The enabled prewarm path executes one real YuNet inference and one real YOLOX
  inference; either failure is reported without skipping the other detector.
- Smoke verification clears the old pointer and accepts only the current
  in-scope runtime log.
- Both success markers are required; missing or unreadable evidence fails.

## Task 5: Show focus and away time with automatic units

**Files**

- `src/webapp/src/components/focusStatus.js`
- `src/webapp/src/components/Dashboard.jsx`
- `src/webapp/src/utils/displayCopy.js`
- corresponding frontend tests

**Acceptance criteria**

- Active payload validation includes away seconds and active timer.
- Poll failures preserve both frozen durations and the last trusted mode.
- Present displays focus; absent displays away from its first trusted second.
- Unknown and stale display the timer selected by `active_timer`.
- One formatter handles the defined minute, hour, and day boundaries in both
  English and Chinese, including English day singular and plural.
- Near-limit styling applies only to fresh present focus time.

## Task 6: Full source and installed-runtime verification

Run from the repository root unless noted otherwise:

- `python -m pytest -q -p no:cacheprovider`
- `npm test` from `src/webapp`
- `npm run lint` from `src/webapp`
- `npm run build` from `src/webapp`
- `git diff --check`
- Python compile checks for changed source files

Then run `RUN.bat` and let the complete Windows build, packaging, installation,
launch, and packaged-runtime smoke verification finish naturally.

The installed application must satisfy all of the following:

- installed build metadata matches the repair commit;
- the backend owns `127.0.0.1:8000`;
- `/api/status` reports the expected packaged runtime and camera state;
- `/api/health/sedentary` includes valid focus, away, and active-timer fields;
- the current packaged runtime log contains successful YuNet and YOLOX
  inference markers and no blocking startup errors;
- live observations never advance a timer during missing, stale, or unknown
  camera intervals.
