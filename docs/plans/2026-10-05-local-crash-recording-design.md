# Local crash recording design

Vantage will collect diagnostic records locally without uploading them. Electron
uses its bundled Crashpad collector before creating windows. Python enables
faulthandler and records uncaught exception stack frames without exception values
or frame locals. Native dumps may contain sensitive memory and must be described
as private, not automatically shared.

All records live under the configured user data directory in `diagnostics`.
Retention limits are ten completed diagnostic records and 200 MiB total, checked
on startup and periodically. Cleanup must not traverse symlinks or delete active
files. Session markers distinguish a normal shutdown from an interrupted session;
the latter is not proof of a crash (force-kill/power loss remain possible).

Next startup shows a non-blocking interruption notice. Settings can open the
diagnostics folder and explains local-only storage and privacy limitations.
Backend abnormal exits are recorded by the parent. No automatic restart loops,
remote upload, registry edits, or changes to user provider settings are added.

Verification includes real isolated Electron and Python fatal-fault subprocesses,
normal/abnormal lifecycle, retention, storage failures and full regression checks.
The installed release must contain the collector and expose diagnostics metadata.
