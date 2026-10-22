# Manual CI verification design

Approved by the user on 2026-10-22: add manual triggers to CI and CodeQL and continue exact-main acceptance.

## Scope

Add a bare `workflow_dispatch:` event to `.github/workflows/ci.yml` and `.github/workflows/codeql.yml`. Retain push/main, pull_request and existing CodeQL schedule. Do not add inputs, jobs, permissions, skip conditions, deployments, or a release trigger.

## Data flow and failure handling

An authorized maintainer dispatches each workflow with `--ref main`. Existing jobs execute normally against the selected ref. Record the actual run head SHA and compare it with remote main; a successful PR run alone is not final-main acceptance. If a dispatch or check fails, diagnose and retry without fabricating success or weakening gates.

## Verification

Use focused contract tests for both manual triggers and retained event/permission boundaries, then the existing full CI and CodeQL. Create a draft PR, review it independently, wait for all necessary checks, ready/merge normally, fetch actual main, dispatch and verify that exact SHA. Close original issues only with their individual repair/test evidence.

