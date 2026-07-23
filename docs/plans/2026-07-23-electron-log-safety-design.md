# Electron Log Safety Design

## Problem

The Electron main process writes each application log entry to a file and then
mirrors the same entry to `stdout` or `stderr`. If the inherited console pipe is
closed, the console write can raise `EPIPE`. The global `uncaughtException`
handler logs that error through the same console path, creating a recursive
error loop that can grow one daily log without bound.

## Goals

- A broken or unavailable console stream must never recurse through the global
  exception handler.
- File logging must remain available when console mirroring fails.
- Electron log files must have a hard size bound and a small, deterministic
  retention budget.
- Oversized legacy Electron logs must be reduced safely during startup.
- The behavior must be covered by deterministic Node tests without launching
  Electron.

## Non-goals

- Changing backend server log behavior.
- Adding a third-party logging dependency.
- Deleting user history, screenshots, or other runtime data.
- Changing the configured Vantage runtime-data directory.

## Considered approaches

### 1. Catch only `EPIPE` around existing console calls

This is the smallest patch, but it leaves unbounded daily files and keeps
logging tightly coupled to global console state.

### 2. Adopt a third-party Electron logger

This provides established rotation features, but adds a production dependency
and migration work for a small main-process surface.

### 3. Extract a small bounded file logger (selected)

Move file and console handling into a pure CommonJS utility. File writes remain
synchronous to preserve ordering during startup and crash handling. Console
mirroring is best-effort and permanently disabled after a broken-pipe error.
Rotation is implemented with standard filesystem operations, so the utility is
small and directly testable.

## Selected design

`createBoundedLogger()` owns all Electron main-process logging:

- The active file remains `electron_YYYY-MM-DD.log`.
- The default maximum active-file size is 10 MiB.
- No more than six matching Electron log files are retained globally, including
  the active file and rotated or older daily files. Combined with the per-file
  limit, this caps retained Electron logs at roughly 60 MiB across days.
- Before each append, the logger rotates if the pending entry would exceed the
  active-file limit.
- After the application has acquired the single-instance lock, the logger scans
  only matching Electron logs in the configured log directory. Oversized
  legacy files are truncated to their most recent 10 MiB, then the oldest
  matching files are pruned to the global file-count limit. A second instance
  therefore cannot clean up a file owned by the primary instance.
- Console mirroring is best-effort. `EPIPE` and destroyed/non-writable streams
  disable further console mirroring without calling the application logger.
  Both synchronous console failures and asynchronous stdout/stderr error events
  are guarded.
- File-write failures are swallowed only after one best-effort console report;
  the fallback itself cannot call back into file logging.

`main.cjs` constructs the logger once, invokes its explicit retention cleanup
only after acquiring the single-instance lock, and keeps the existing
`log.info`, `log.warn`, and `log.error` call sites unchanged.

## Error flow

```text
application event
  -> bounded file append
  -> best-effort console mirror
       -> EPIPE: disable console mirror and return
       -> other error: disable console mirror and return

uncaught exception
  -> bounded file append
  -> console mirror only if still healthy
```

No failure path re-enters the application logger.

## Tests

Pure Node tests will verify:

1. A console method that throws `EPIPE` is called once, is then disabled, and
   does not prevent subsequent file entries.
2. Appending beyond a small injected test limit rotates the active file.
3. Rotation retains no more than the configured number of backup files.
4. Startup bounds an oversized legacy Electron log.
5. Unrelated files in the log directory are never modified.

The existing webapp Node test suite, lint, and production build remain required.
The packaged application must also be rebuilt, installed, launched with a
deliberately broken inherited output pipe, and checked for bounded log growth.
