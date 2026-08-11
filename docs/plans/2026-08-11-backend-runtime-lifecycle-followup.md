# Backend Runtime Lifecycle Follow-up Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the fixed backend runtime venv immutable to shared consumers and ensure every launcher-held target-venv process owns a real shared lifecycle lease.

**Architecture:** The exclusive environment synchronizer becomes the only owner of target-venv mutation, including removal of conflicting packaging DLLs before final validation and state publication. Build and launcher consumers either run through the bootstrap lock supervisor or use bootstrap Python directly; the macOS development server always uses the fixed runtime interpreter.

**Tech Stack:** Python 3.13, pytest, Windows batch, Bash, OS-backed backend runtime lifecycle lock.

---

### Task 1: Make backend builds read-only against the target venv

**Files:**
- Modify: `tests/test_backend_runtime_packaging.py`
- Modify: `tests/test_sync_backend_runtime_environment.py`
- Modify: `src/scripts/build_backend_runtime.py`
- Modify: `src/scripts/sync_backend_runtime_environment.py`

1. Add tests proving the shared build consumer never calls the target-venv DLL remover and that synchronization removes conflicting DLLs before publishing reusable state.
2. Run the focused tests and confirm they fail for the missing ownership boundary.
3. Remove target-venv mutation from `build_backend_runtime.py`; invoke it only inside the exclusive synchronizer before final probes/state write.
4. Re-run the focused tests and the real shared/exclusive lock regression.

### Task 2: Supervise launcher target-venv commands

**Files:**
- Modify: `tests/test_launcher_safety.py`
- Modify: `RUN_DEV.bat`
- Modify: `RUN.sh`
- Modify: `RUN_DEV.sh`

1. Add static contract tests requiring target-venv cleanup to pass through bootstrap `run_with_backend_runtime_lock.py`, requiring Windows frontend background launch to use bootstrap Python, and rejecting `PYTHON_BIN` overrides.
2. Run the tests and confirm all new assertions fail against the current launchers.
3. Route cleanup through the bootstrap shared-lock supervisor, switch stdlib-only frontend launch to bootstrap Python, and hard-bind the macOS development server to `BACKEND_RUNTIME_PYTHON`.
4. Re-run launcher tests plus Bash syntax checks.

### Task 3: Verify and commit

**Files:**
- Test: `tests/test_backend_runtime_packaging.py`
- Test: `tests/test_sync_backend_runtime_environment.py`
- Test: `tests/test_backend_runtime_lock.py`
- Test: `tests/test_launcher_safety.py`

1. Run the complete targeted lifecycle suite and `git diff --check`.
2. Inspect the final diff for forbidden-file changes and a clean ownership boundary.
3. Create one detailed commit covering the lifecycle fix and its regressions.
