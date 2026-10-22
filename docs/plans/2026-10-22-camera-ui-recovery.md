# Camera preview and analysis recovery

Scope: #132 and #134. No hardware, model installation or deployment.

1. Separate device-online state from actual image transport state. Claim Live
   only after the current image has decoded. Recover failed streams with five
   exponential delays (1, 2, 4, 8, 15 seconds), then offer manual retry.
2. Fence image callbacks by preview session and attempt. Hide, privacy withdrawal
   and unmount cancel timers; late events cannot revive a retired stream.
3. Treat authoritative face progress idle as a lost/no-longer-running job,
   release the local spinner, refresh the saved report, explain the interruption
   and allow another analysis. Queued/running and temporary transport failures
   must not be misreported as completion.
4. Red-green deterministic lifecycle/progress tests, frontend lint/tests/build,
   independent review, and a real production Electron fault-injection smoke.

The initial lifecycle/progress tests failed before implementation. Real UI
acceptance will use synthetic JPEG frames and a loopback server, not the camera.
