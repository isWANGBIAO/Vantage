# Focus Presence Regression Design

## Goal

Keep focus time reliable when a seated user turns away from the camera or their
face leaves the frame, account for trusted away time separately, and never
count camera outages or stale frames as either focus or away time.

The solution must remain self-contained in the packaged OpenCV runtime. It must
not restore the removed PyTorch or Ultralytics dependency stack.

## Confirmed regressions

Recent presence and camera changes exposed several interacting defects:

- the YuNet migration narrowed "person present" to "face visible", so a seated
  user whose head was outside the frame could be treated as absent;
- the API derived duration from wall-clock start timestamps, which could drop
  time on absence and later add unknown or away gaps back into focus time;
- a cached camera frame had no publication timestamp and could be reused after
  the camera stopped producing new frames;
- the monitor waited the normal 60-second interval even when no usable frame
  existed, delaying startup and reconnect recovery;
- capture or inference failures were indistinguishable from confirmed absence;
- short restarts, Unicode media paths, camera warmup, and physical/renderer
  camera ownership each had adjacent state-loss or stale-data failure modes;
- the dashboard exposed only focus minutes and replaced confirmed absence with
  a static label instead of showing away time.

## Presence signals

YuNet and the existing landmark geometry remain the face and camera-facing
signals. A bundled OpenCV Zoo YOLOX int8 model supplies body-aware presence
without adding a second inference runtime.

- **face present**: YuNet finds a face at the presence threshold;
- **body present**: YOLOX finds a person at the body threshold;
- **camera-facing**: a YuNet face also passes the landmark geometry filter;
- **absent**: both presence detectors ran successfully and found nothing;
- **unknown**: capture failed, both detectors could not produce a trustworthy
  negative result, or the input frame was missing or stale.

A positive result from either presence detector is sufficient. One detector's
failure cannot erase a positive result from the other. A negative observation
is accepted only when both detectors completed successfully, preventing a
missing model or unsupported operator from being interpreted as absence.

The YOLOX model, its Apache-2.0 license, and packaging metadata live under
`src/models`. It is loaded through OpenCV DNN; Torch, Ultralytics, and
ONNX Runtime are not required.

## Trusted timer state machine

Focus and away are independent accumulated durations. A timestamp identifies
the currently trusted segment, but elapsed values are never reconstructed from
the original session start.

- `present` settles the previous trusted segment, clears the current away
  episode, and runs the focus timer;
- `absent` settles focus and runs the away timer immediately;
- `unknown` pauses whichever timer was active without adding the unknown gap;
- a stale monitor heartbeat settles only to `heartbeat + timeout`, then freezes;
- after 120 trusted away seconds the old focus session is cleared, while the
  away timer continues;
- returning before 120 trusted away seconds resumes the existing focus session;
- wall-clock rollback clears invalid accumulated state and starts from the new
  trusted observation.

`continuous_sit_start` is retained only as focus-session identity for backward
compatibility. Notifications and API duration values use the accumulated focus
seconds. `active_timer` exposes the last trusted `focus`, `away`, or `none`
mode, allowing unknown and stale responses to display a frozen timer without
claiming a fresh measurement.

The runtime state file is atomic and versioned. Version 2 stores settled focus
and away durations plus the last trusted mode. A restart can restore a candidate
only after a fresh matching trusted observation inside the existing grace
window; process downtime is never counted. Version 1 focus records remain
readable for migration.

## Camera frame lifecycle

The camera loop is the sole physical-camera reader. Every published frame is
paired atomically with a monotonic publication timestamp. Installing, retiring,
reopening, replacing, or shutting down a camera clears the frame and timestamp
together.

The monitor accepts a frame only when its timestamp is finite, not in the
future, and no older than five seconds. Missing or stale frames are passed to
the monitor as unavailable observations. A trustworthy `present` or `absent`
result uses the normal 60-second interval; missing, stale, unknown, or failed
cycles retry after two seconds.

Renderer-camera liveness also uses monotonic time. Renderer upload publishes
its liveness timestamp and monitor-frame timestamp from the same clock sample,
so wall-clock corrections cannot hold renderer ownership indefinitely or make
the monitor consume an old renderer frame.

## API and dashboard

`/api/health/sedentary` keeps the original focus fields and adds:

- `away_duration_seconds`: trusted seconds in the current away episode;
- `active_timer`: `focus`, `away`, or `none`.

The dashboard shows focus time for present observations and away time from the
first trusted absent observation, including the two-minute focus grace period.
Unknown and stale states show the frozen timer selected by `active_timer`.

Both timers use one seconds-based formatter:

- under 60 seconds: under one minute;
- under one hour: whole minutes;
- under one day: hours and an optional non-zero minute remainder;
- one day or more: days and an optional non-zero hour remainder.

Only a fresh present focus timer can receive the near-limit warning treatment.

## Packaged-runtime validation

When packaged smoke verification enables camera-detector prewarming, startup
runs one real blank-frame inference through both YuNet and YOLOX. The verifier
deletes the previous log pointer before launch, accepts only a log inside the
current smoke-data server-log directory, inspects the current launch section,
and requires both inference-success markers. Missing, unreadable, empty,
out-of-scope, or incomplete logs fail closed even if `/api/status` responds.

## Test strategy

Regression coverage includes:

- face-only, body-only, and combined presence without double counting;
- detector failure, malformed output, and non-finite YOLOX boxes;
- present/absent/unknown/stale timer transitions and exact 120-second edges;
- restart migration, matching-only recovery, persistence failure, and rollback;
- frame publication, TTL rejection, renderer ownership, and shutdown clearing;
- two-second recovery versus 60-second trusted monitoring;
- real packaged YuNet and YOLOX inference and fail-closed log validation;
- focus/away dashboard selection, polling degradation, automatic units, and
  English/Chinese day singular and plural output;
- Unicode media handling, warmup recovery, and storage failure isolation.

Final verification includes the full Python and frontend suites, lint and
production builds, the complete Windows install flow, installed metadata,
fresh runtime logs, endpoint probes, and live camera/timer observation.
