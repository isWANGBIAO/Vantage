# Independent Windows launch correction

## Root cause scope

The previous observer requested job breakaway but did not remove inherited
Desktop App process-tree policy or verify actual process ownership. Windows job
isolation and Desktop Bridge package-runtime isolation are different mechanisms.
The current Windows heartbeat interruption coincides with a forced package
update; that correlation is strong evidence, not a per-process terminating actor.

Primary references:
- https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
- https://devblogs.microsoft.com/oldnewthing/20190425-00/?p=102443
- https://github.com/openai/codex/blob/main/codex-rs/windows-sandbox-rs/src/proc_thread_attr.rs

## Implementation

1. Add a standard-library Windows native launcher. Resolve the interactive shell
   using GetShellWindow; validate its process image, user and session. Explicitly
   set Explorer as parent and Desktop App ENABLE_PROCESS_TREE. Create suspended,
   verify the actual child's no-job/no-package/shell-parent identity, then resume.
   Close handles on every path; failure must not fall back to ordinary spawn.
2. Use it for the existing observer's launch; readiness includes actual verified
   identity rather than a requested flag. Keep the backend owned by Electron.
3. Add early installed-app self-check and one-time handoff before the singleton
   lock or diagnostic-session creation, so direct execution, installer completion
   and login launch all follow the same rule. A failed handoff is visible and
   cannot be reported as independent success. Do not change supervised dev mode.
4. Make RUN.bat explicitly use the native installed launch mode. Do not persist
   services/tasks, change audit/security policies, or disable application updates.
5. Test first: identity validation, Unicode quoting, cleanup/failure, synthetic
   kill-on-close job launcher termination, Desktop App policy inheritance,
   observer survival and existing exit evidence/recovery. Never terminate Codex,
   Explorer or unrelated applications to test this feature.
6. Run scoped/full regressions and independent review, bump the patch release,
   integrate into the build checkout, run RUN.bat to natural completion, then
   verify installed main/observer native identity, heartbeats and config hashes.

## Limits

No active interactive shell or insufficient process-create access is an explicit
launch error, not permission to bypass security. Even independent processes cannot
survive power loss, arbitrary administrator termination or storage destruction.
Persist bounded boolean/enum/PID/time evidence, never package names, full process
paths, command lines, environment values or secrets.

## Packaged acceptance correction

The first packaged run exposed a probe side effect absent from mocked spawn
tests: libuv initializes its own anonymous job on an ordinary spawn and enrolls
the spawning process itself. A regular identity-probe spawn therefore changed
the main process from no-job to its own job before inspection, causing a false
failure. Keep strict startup identity checks; make only the short-lived startup
probe/relay helpers detached. Add a real Node/native probe control test, not just
an options assertion. Later application-owned jobs remain valid. Primary source:
https://github.com/libuv/libuv/blob/v1.x/src/win/process.c
