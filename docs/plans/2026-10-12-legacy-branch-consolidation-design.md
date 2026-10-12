# Legacy branch consolidation design

## Goal

Move the remaining behavior of `feature/never-stop-demo` into the current
Vantage `main` without replacing its newer backend, CLI/MCP, or embedded Never
Stop page. Retire the two obsolete local feature branches after verification.

## Scope and data flow

All personal prompt reads use `DataLoader.resolve_data_path`. The action-plan
source fingerprint includes the system prompt. A successful, complete plan
records the fingerprint captured before generation in its metadata. On startup,
the scheduler compares that saved fingerprint with the current sources rather
than treating an arbitrary existing plan as current. An older plan without a
valid fingerprint remains eligible for regeneration when checks are enabled.

Project progress reads the resolved project prompt afresh for every request.
Its Git activity is limited to that prompt's directory; a packaged activity
snapshot applies only to the matching bundled template. The page refreshes on
mount, window focus, and explicit request through a single in-flight request.

## Safety and error handling

Missing or unreadable required files remain retryable errors. A failed or
incomplete generation never certifies a source revision. The scheduler keeps
its existing digest-only runtime metadata; prompt text, credentials and local
paths do not enter it. The private `scripts/leg_hair` workstream and stale
version/icon changes from the old checkout are excluded from public commits.

## Verification

Use focused Python tests for source resolution, plan revision persistence,
restart behavior and project activity. Use focused frontend tests for
single-flight refresh and focus lifecycle. Then run the full Python suite,
frontend lint/tests/build and Never Stop tests before switching the primary
checkout to `main` and removing the obsolete branches/worktree.
