# Manual CI verification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow maintainers to run unchanged CI and CodeQL jobs against main when an automatic push run is absent.

**Architecture:** Add workflow_dispatch to both existing event maps. Keep every existing job, event and permission unchanged. Validate through contract tests and exact-main runs after a reviewed normal merge.

**Tech Stack:** GitHub Actions YAML, existing pytest workflow contracts, GitHub CLI.

---

### Task 1: Add and verify manual triggers

**Files:** Modify `.github/workflows/ci.yml`, `.github/workflows/codeql.yml`, `tests/test_ci_workflow.py`.

1. Add parameterized pytest contracts requiring a top-level bare workflow_dispatch event in both files. Preserve push/main, pull_request, CodeQL schedule and current permissions; reject dispatch inputs that bypass jobs.
2. Run `python -m pytest -q tests/test_ci_workflow.py`; observe expected missing-trigger failures before changing YAML.
3. Insert only `  workflow_dispatch:` immediately below each `on:` line.
4. Rerun the workflow tests, Ruff and diff checks. Compare parsed existing jobs/permissions and remaining triggers against the base commit; they must be identical.
5. Commit with detailed root cause, scope and verification evidence. Independently review spec compliance then quality. Push and create draft PR; retain all required checks.

### Task 2: Complete exact-main acceptance

1. Wait for all PR CI and CodeQL checks on the actual head; ready and merge normally without bypass or force push.
2. Fetch main, verify remote/local SHA and source-tree identity. Dispatch CI and CodeQL using `gh workflow run ci.yml --ref main` and `gh workflow run codeql.yml --ref main` when needed.
3. Verify both run head SHAs equal actual remote main and all required jobs succeed.
4. Recheck the original issue inventory; attach individual repair commits, test paths/commands and final main run links before closure. Do not close newly discovered or unmapped issues without diagnosis.
5. Publish the final per-issue report, verify fresh issue/PR state and a clean root main. No installation, deployment or security-setting changes.

