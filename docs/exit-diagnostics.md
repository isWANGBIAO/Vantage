# Local exit evidence

Vantage keeps diagnostics under the configured user-data directory. It does not
upload them, install a system service, or change Windows audit/security policy.
Native crash dumps can still contain private memory; do not publish them.

## Evidence layers

- `diagnostics/electron-session.active.json` and `diagnostics/sessions/` hold
  atomic, synchronously flushed session metadata. A heartbeat advances every
  five seconds. Normal quit writes a clean lifecycle event and removes the
  current marker. Interrupted recovery preserves the old session identity and
  last heartbeat, and records discovery time separately from unknown exit time.
- `diagnostics/lifecycle/exit-*.json` records bounded metadata, not arguments,
  environment variables, prompts or exception values. Main/backend identities
  are separate; unexpected code zero is not silently treated as normal.
- On Windows a lightweight observer in the existing backend runtime holds
  process handles for the desktop main process and its owned backend. Its
  acknowledgement is refreshed every two seconds; the desktop checks health
  without repeatedly spawning identity probes. PID reuse cannot make a new
  process inherit an old handle's identity.
- `diagnostics/electron/` and `diagnostics/python/` retain existing local crash
  evidence. A dead Python writer's empty record is converted into interruption
  metadata before removal instead of silently erasing the only clue.

## Interpreting coverage

`breakaway` means the observer requested independent Windows job execution.
If the launching job forbids breakaway, `inherited-job` is explicitly logged as
degraded isolation. Reused/external backend services without an owned process
handle are explicitly logged as main-only coverage. Other platforms currently
use durable heartbeat recovery and report the observer as unsupported.

Failed storage, failed initialization, lost observer heartbeat and unavailable
process handles are explicit warnings. No observer can promise immediate writes
after power loss or if every writer is forcibly killed. The durable session can
then establish an interruption at the next start, but not an exact exit time,
exit code or terminating actor. Filesystem failure/deletion can defeat recovery.

Lifecycle history is limited to 100 records / 5 MiB; old inactive session
snapshots to 20 / 5 MiB. Live evidence is protected, with a warning if it exceeds
budget. Existing native/Python crash reports retain their separate 10-record /
200 MiB policy.

## Verification

```powershell
node --test src/webapp/src/utils/crashDiagnostics.test.js src/webapp/src/utils/exitObserver.test.js
python -m pytest -q tests/test_exit_observer.py tests/test_crash_diagnostics.py tests/test_run_server_background.py
npm --prefix src/webapp run test:crash-diagnostics
```

Tests terminate only isolated synthetic processes. They cover normal quit,
native crashes, backend/main force termination, losing all evidence writers,
interruption recovery, PID reuse, storage failures, bounded history, metadata
privacy and legitimate atomic file-publication races. Packaging and installed
readiness must still be verified separately for every release.
