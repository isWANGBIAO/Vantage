# Trusted Location Cross-Check and Fixed 1 Hz Performance Design

## Context

The location-trust branch already removes the hardcoded Shanghai fallback,
validates WinRT metadata, and refuses to write untrusted GPS metadata. One gap
remains: a browser sample can currently be accepted for AQI without independent
evidence even though the browser Geolocation API does not identify its source.

The installed application also exposes three background modes. In `prewarm`
mode, YuNet foreground detection and the heavier live face analysis can run at
roughly 10 Hz even when their consumers are hidden. This consumes far more CPU
than the feature needs and presents a choice that users should not have to
understand.

## Confirmed Goals

- Keep one fixed high-performance behavior instead of `balanced`, `prewarm`,
  and `power_saver` choices.
- Preserve the old prewarm availability semantics: hidden dashboard and face
  history views stay mounted after lazy loading, live face analysis continues
  without an active viewer, and YuNet may continue without a video-stream
  client when face boxes are enabled.
- Limit both YuNet foreground inference and live face analysis to at most one
  invocation per second. Camera capture, stream frame rate, photo cadence,
  focus state, and the two-minute away grace period do not change.
- Require browser AQI coordinates to agree with a fresh trusted backend sample.
- Release the merged result as `v1.0.65` only after tests, installed-flow
  verification, CPU measurement, PR review, and CI pass.

The action-plan model failure, occasional multi-monitor `BitBlt` failure, and
stale box on an offline frame are explicitly outside this change.

## Fixed Performance Behavior

`src/server.py` will define one named one-second inference interval and remove
the background-mode cache, sanitizer, loader, and mode branches. The live face
loop always remains eligible while the server is running. The YuNet loop is
eligible whenever green face boxes are enabled; it no longer requires a video
stream client. Turning boxes off immediately clears the cached box list and
keeps YuNet idle.

Each loop records the monotonic start time of its last inference. Before the
next inference starts, it waits until at least one second has elapsed. Measuring
start-to-start rather than sleeping a fixed second after completion both proves
the maximum 1 Hz rate and avoids accumulating an extra second on top of model
runtime. Idle waits remain interruptible through the existing server-running
condition.

The frontend retains background component preloading and mounting, but removes
all dependence on a selected mode. Once settings are loaded, background tab
chunks preload; once ready, the existing hidden Dashboard and FaceHistory
components mount exactly as they do in prewarm mode today. No setting or copy
suggests alternative performance strategies.

## Settings Schema Migration

The persisted settings schema becomes version 2 in both Python and Electron
normalizers. `background_mode` is removed from defaults, sanitized output, save
payloads, bridge state, React state, and the Settings form. Reading a version 1
file with `balanced`, `prewarm`, or `power_saver` preserves every other valid
setting but silently drops the legacy key; the next save writes version 2.

The browser-only settings fallback similarly removes `backgroundMode` from its
normalized and stored state. The Performance section keeps the action-plan
auto-generation switch, but the background-strategy row and its English and
Chinese translation keys are removed. Existing users need no prompt and no
separate migration file.

## Browser and Backend Location Cross-Check

`/api/aqi` keeps the existing optional `lat`, `lon`, `accuracy`, and
`timestamp_ms` query parameters and the existing response keys.

The backend location adapter will expose a metadata-preserving asynchronous
entry point that returns a trusted `LocationSample` or `None`. Existing tuple
wrappers remain compatible for EXIF and current callers. This prevents the AQI
endpoint from reconstructing a fake timestamp or accuracy after the WinRT or
explicitly configured sample has been validated.

The endpoint distinguishes two request forms:

1. If all four browser fields are absent, fetch a fresh trusted backend AQI
   sample and use it directly.
2. If any browser field is present, require all four. Validate finite legal
   coordinates, positive accuracy no greater than 1,000 metres, and a timestamp
   no older than 120 seconds. Then fetch a trusted backend AQI sample in the same
   request.

For the second form, accept the request only when the absolute sample timestamp
skew is no greater than 30 seconds and the effective separation is no greater
than 1,000 metres:

```text
effective distance = max(0, centre distance
                            - browser accuracy radius
                            - backend accuracy radius)
```

An accepted cross-check always uses the trusted backend coordinate for the
Open-Meteo request and response. A missing backend sample, partial or invalid
browser metadata, excessive time skew, or excessive effective distance returns
the existing `status="unavailable"` payload with null coordinates and does not
call Open-Meteo. Browser-only coordinates are never accepted.

Application logs retain source/status/reason information without raw
coordinates, and Uvicorn access logging remains disabled so query parameters do
not leak through request logs.

## Failure Handling and Compatibility

- Backend permission denial, timeout, incomplete WinRT metadata, or untrusted
  source remains a normal unavailable result.
- Static coordinates remain an explicit opt-in backend source and participate
  in the same browser consistency check when browser fields are supplied.
- AQI upstream failures preserve the current response structure and privacy
  behavior.
- No API query field or JSON response key is removed.
- Model loading/prewarming, camera capture, video encoding, focus persistence,
  and EXIF trust thresholds remain unchanged.

## Verification and Release Gate

Implementation follows TDD for location matching, loop throttling, schema
migration, and frontend removal. Targeted Python and focused frontend tests run
before the complete Python suite, frontend suite, lint, and production build.

`RUN.bat` must finish naturally. After the installed backend is stable for two
minutes, locate its PID through the port 8000 listener, sample that process's CPU
time for 30 seconds, and divide the CPU-time delta by elapsed wall time and the
logical processor count. Its normalized average must be below 25%; a missing or
restarted PID invalidates the measurement. Also verify `/api/status`,
`/api/health/sedentary`, trusted and unavailable `/api/aqi` paths, packaged
version/commit, runtime manifest, and absence of raw coordinates in fresh logs.

Only then push `feature/location-trust`, open a ready PR to `main`, complete
specification and quality review, and wait for Python 3.11/3.13, frontend build,
and CodeQL checks. Merge with a normal merge commit, fast-forward the local
`main`, create and push annotated tag `v1.0.65`, and verify the release assets,
blockmap, and `SHA256SUMS.txt`. A CPU result at or above 25% blocks pushing,
merging, tagging, and release until investigated.
