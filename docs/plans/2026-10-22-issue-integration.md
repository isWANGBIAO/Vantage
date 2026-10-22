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
