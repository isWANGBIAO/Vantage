# Open-issue repair integration

The starting inventory contained 95 open issues (#43–#137), independently
retrieved from GitHub. Six have been individually verified and closed on the
already-green main commit 48e03f7. The remaining 89 stay open pending integrated
verification, not merely creation of repair PRs.

## Integration policy

- Preserve root-cause repair commits using normal merges into the integration
  branch. Per-issue mapping is maintained in issue-resolution-tracker.md.
- Supersede batch drafts with one final draft PR so the exact combined tree is
  tested, including all platform jobs. Cancel only superseded workflow heads.
- Do not change CI gates, force-push, deploy, access real cameras/models, or
  modify private runtime data. All new fault-injection inputs are synthetic.
- Independently review cross-batch contracts: provider DTO and routing, plan
  budget and retry/publication, image transport and observation ownership,
  finance dates, migration failure recovery, cache authorization and contents.
- Run full Ruff/Python, frontend lint/tests/build, Never Stop, actual Electron
  protocol and production React fault-injection smoke tests on the combined tree.
- Convert the final draft only after necessary CI is green. Normally merge to
  main, fetch its exact SHA and verify that SHA's CI and CodeQL again.
- Close each issue with its own scope-specific evidence. Never close on the
  basis of the aggregate number alone.

## Intermediate evidence

Before the final migration and UI recovery merges: full Python 2040 passed,
16 skipped and 101 subtests; Ruff passed. Frontend lint/tests/build passed;
real Electron protocol and eight-page production UI (291 synthetic requests,
zero renderer errors) passed. These are intermediate, not final acceptance.

An existing ten-real-process Never Stop test repeatedly exceeded one shared
15-second deadline on Windows. The diagnosis and progress-based test repair
must preserve process ownership/cleanup and the ten-attempt contract; simply
increasing the timeout or removing the scenario is not acceptable.

## Final local acceptance before CI

- Combined production code: full Python 2094 passed, 16 POSIX-only skips,
  101 subtests; Ruff passed. The pre-existing Starlette deprecation warning
  remains non-failing.
- Frontend: lint, 649 tests and production build passed.
- Never Stop: 171/171 passed with default parallel execution. The diagnosed
  retry test now checks each real state transition, without changing production
  cleanup/backoff or increasing the existing per-progress timeout.
- Actual Electron app protocol passed; eight production React pages completed
  381 synthetic requests with zero renderer errors. Real TCP multipart failure,
  hidden-stream cleanup and queued/transport-failed/running/idle analysis
  recovery passed in the combined harness alongside provider-settings cases.
- Independent cross-contract review: 117 Python and 17 usage UI tests passed;
  partial/invalid usage, nullable DTOs and output-only speed points covered.
- Additional three build-cache issues were individually closed after exact-main
  f45ece3 CI and CodeQL passed; nine issues closed, 86 remain open at this
  pre-merge snapshot. The issue links and final PR record carry subsequent live
  closure status.

No final CI or main success is claimed in this pre-merge acceptance record.

## Python 3.13 CI fixture correction

The first combined CI head bbbda27 passed Python 3.11, frontend, arm64 and
CodeQL, but one Python 3.13 test failed: its global os.walk fault injection also
intercepted tempfile cleanup (Python 3.13 shutil uses os.walk there). The
synthetic PermissionError lacked a filename, so cleanup raised TypeError rather
than exercising only the intended source-read failure.

An unrelated-tree completeness assertion first failed in both root/child
variants. Fault injection is now limited to the synthetic legacy source, uses
an OS-shaped error and explicitly proves that source fault still occurs.
All original data/config rollback and same-source retry assertions remain.
Independent six-variant review plus 86 focused settings/media/storage tests and
Ruff passed. No production code or CI gate changed; the new exact head must
rerun the complete CI matrix.
