# Focus Presence Regression Design

## Goal

Restore reliable continuous focus-time tracking after the YuNet migration while
keeping the backend lightweight and preserving the stricter camera-facing face
classification for features that actually need it.

## Confirmed regressions

The YuNet migration reused one signal for two different meanings. A face had to
pass both a high confidence threshold and a frontal-landmark geometry filter
before the monitor treated the user as present. Runtime sampling showed that a
visible seated user was detected by the raw YuNet output consistently at a
moderate threshold, while the combined high-threshold frontal filter rejected
the same frames. Periodic false negatives then exceeded the two-minute grace
period and reset focus time.

The same recent camera and Unicode changes exposed four adjacent defects:

- capture or detector failures were indistinguishable from confirmed absence;
- the timer existed only in memory and was lost on every short restart;
- Unicode-safe image writing was added without Unicode-safe image reading;
- black-frame recovery could reopen a camera before its warmup window ended,
  and monitor capture could bypass the warmed, published frame.

## Chosen approach

Keep the bundled YuNet model and split its outputs by product meaning:

- **presence**: any visible YuNet face at a moderate presence threshold;
- **camera-facing**: a face that also passes the existing landmark geometry
  filter;
- **unknown**: no trustworthy observation because capture or inference failed.

This avoids restoring the large PyTorch/Ultralytics packaging stack and avoids
adding a second body-detection model. The frontal filter remains available for
overlay or analysis behavior, but it no longer controls focus-time presence.

## Data flow

The camera loop owns physical camera reads. Only a non-dark frame published
after warmup becomes the monitor's sampling input. The periodic monitor copies
that frame and asks the photo service for a tri-state presence observation.

For each observation:

- `present` starts or continues the focus session and clears absence debounce;
- `absent` starts an absence window and resets only after the grace period;
- `unknown` preserves the current session and does not advance an absence
  window.

The monitor persists only the minimum recovery state under the configured
runtime directory. A new process restores the prior start time only after a new
positive observation and only when the last positive observation is within the
existing grace period. Corrupt, future-dated, or stale state is ignored. This
keeps short application restarts continuous without claiming focus through long
unobserved downtime.

The health endpoint reports the latest observation status separately from the
timer state. The dashboard can therefore distinguish confirmed absence from a
temporarily unavailable measurement.

## Error handling and storage

Photo storage is independent from presence. If the detector confirms presence
but saving fails, the timer still advances and the last valid media path remains
unchanged. Stored photos are decoded with `numpy.fromfile` plus
`cv2.imdecode`, which supports Unicode Windows paths.

During camera warmup, dark frames neither publish nor count toward the reopen
threshold. After warmup, the normal consecutive-dark-frame policy resumes.

## Test strategy

Regression tests cover:

- non-frontal and moderate-confidence faces count as presence but not as
  camera-facing faces;
- capture/inference failures produce `unknown`, not `absent`;
- intermittent unknown observations do not clear focus time;
- confirmed absence still resets after the grace period;
- short-restart recovery, stale/corrupt/future state rejection;
- photo-save failure preserves both presence and the last media path;
- Unicode image reading;
- warmup dark frames cannot trigger an early reopen;
- monitor sampling uses the warmed published frame;
- endpoint and dashboard behavior for present, absent, and unknown states.

Final verification includes focused tests, the full Python and frontend suites,
lint/build checks, the complete Windows install flow, installed metadata and
endpoint probes, fresh logs, and a live focus-time monotonicity check.
