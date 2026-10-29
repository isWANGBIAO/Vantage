# Exit diagnostics design

Approved scope: local-only two-layer exit evidence, without a system service,
scheduled task, security-policy changes, telemetry, or new large dependencies.

## Architecture

Electron maintains an atomic per-session lifecycle snapshot and a periodic
heartbeat. Preserve the interrupted session's identity, start/last-active times,
process IDs, parent PID and shutdown phase when recovering after restart.
Normal shutdown is explicitly distinguished from an unexplained interruption.

A lightweight standard-library Python observer, dispatched early by the existing
bundled backend executable, holds native Windows process handles for the main and
backend processes. It records actual observed exit times and exit codes. A short
launcher requests Windows job breakaway and detached execution; if breakaway is
denied, record degraded isolation rather than claiming independence. No elevation
or new installed runtime is required. Unsupported platforms retain heartbeat
recovery and explicitly report observer availability.

The observer never terminates or restarts application processes. It exits when
the observed processes exit. Readiness is acknowledged and failures are visible.
Persist only bounded allowlisted metadata, never arguments, environment, error
messages, screenshots, prompts or arbitrary file contents. Reject symlinks,
reparse points and unsafe session identifiers. Use separate atomic files to avoid
Electron/observer write races. Bound lifecycle history independently of native
crash-report retention, preserving current live evidence.

## Guarantees and limits

Verify normal quit, unexpected exit (including code zero), native crash, forced
main/backend termination, and observer-plus-application termination. When all
writers stop, the last durable heartbeat remains recoverable at next startup.
Do not label recovery time as exit time or invent a terminating actor. Power loss,
storage failure, and explicitly deleting evidence cannot be absolutely covered;
report storage/observer failures instead of silently promising coverage.

## Delivery

Unit tests first, isolated real-process termination tests, existing native crash
smoke, frontend/Python regression checks, independent review, patch version bump,
then the complete Windows RUN.bat build/install/start flow. Verify the installed
version, build identity, active heartbeat, observer readiness and unchanged user
configuration separately. Do not upload private diagnostic data.
