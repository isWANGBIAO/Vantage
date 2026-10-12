# Legacy Branch Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve the remaining prompt, source-revision and project-progress behavior from the old Never Stop branch in current Vantage `main`, then retire both obsolete local branches.

**Architecture:** Keep the versioned backend API and backend-owned action-plan scheduler. Reuse `DataLoader.resolve_data_path` for personal sources; pass the already-captured source digest through the job adapter to the generator and publish it only with a complete plan. Reconcile scheduler metadata against the saved plan on restart. The React progress page owns one abortable single-flight refresher.

**Tech Stack:** Python/FastAPI/pytest, React/Vite/Node tests, PowerShell/Git.

---

### Task 1: Personal source paths and project progress

**Files:** `src/utils/data_loader.py`, `src/backend/projects.py`, `tests/test_system_prompt_sources.py`, `tests/test_project_progress_endpoint.py`.

1. Add failing tests: personal `Prompt_System.md` takes precedence and is reread; project progress reads the resolved personal project prompt, never falls back to unrelated cwd Git history or bundled activity, while a bundled prompt can still use its matching snapshot.
2. Run `python -m pytest -q tests/test_system_prompt_sources.py tests/test_project_progress_endpoint.py` and confirm the new cases fail for the expected behavior.
3. Resolve both prompt paths with `DataLoader.resolve_data_path`; use only the resolved prompt directory for Git, and gate the packaged snapshot by resource-root identity. Fix the project header Boolean precedence while touching that parser.
4. Repeat focused tests and commit only these files with a detailed message.

### Task 2: Plan fingerprint, saved revision and restart

**Files:** `src/backend/action_plans.py`, `src/backend/application.py`, `src/services/action_plan_jobs.py`, `src/services/action_plan_scheduler.py`, `src/scripts/run_prompt.py`, `tests/test_action_plan_source_revision.py`, `tests/test_action_plan_scheduler.py`, appropriate generation/job/store tests.

1. Add failing tests showing that `Prompt_System.md` changes the fingerprint, a complete saved plan carries the pre-generation SHA-256 revision, failed output does not certify it, and a previously saved/legacy plan is compared correctly on scheduler restart.
2. Run the focused Python tests and verify the intended failures.
3. Pass the job's captured revision to the internal generation adapter (never to public request fields), set a validated child-process environment value, write it in plan metadata, and expose current/saved revision through the versioned source-revision API. Reconcile digest-only scheduler state against the complete saved plan rather than recording the current file revision as an arbitrary baseline. Preserve zero-interval semantics and retry-after-failure behavior.
4. Repeat focused tests and commit only these files with a detailed message.

### Task 3: Progress-page refresh lifecycle

**Files:** `src/webapp/src/components/ProjectProgress.jsx`, `src/webapp/src/components/ProjectProgress.test.js`, `src/webapp/src/utils/projectProgressRefresh.js`, `src/webapp/src/utils/projectProgressRefresh.test.js`.

1. Add failing tests for mount/focus/manual refresh, one in-flight request, abort on unmount, and no stale-state update after unmount.
2. Run `npm --prefix src/webapp test` and confirm the focused new cases fail as expected.
3. Implement a small single-flight helper, subscribe to focus, and make the component's fetch abortable. Do not change the backend-owned Action Plan scheduler or reintroduce the old frontend timer.
4. Repeat frontend tests, lint and build, then commit only these files with a detailed message.

### Task 4: Integration verification and Git cleanup

1. Run `python -m pytest -q`, `npm --prefix src/webapp run lint`, `npm --prefix src/webapp test`, `npm --prefix src/webapp run build`, and `npm --prefix src/webapp run never-stop:test` from current `main`. Review `git diff`, commits and public-file privacy.
2. Preserve the old checkout's unrelated private scripts and obsolete dirty changes locally without committing them; archive the clean managed `main` worktree via Codex; switch the original checkout to `main`.
3. Verify every meaningful old-branch change is either present or intentionally obsolete; then delete `feature/claude-glm-native-stability` and `feature/never-stop-demo`. Verify final status, branch list and worktree list. Do not push or reinstall without a separate request.
