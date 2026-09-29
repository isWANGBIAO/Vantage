# Repository Agent Notes

This repository is public-facing. Do not commit private prompts, health exports,
screenshots, photos, finance workbooks, local logs, API keys, or machine-specific
paths.

- Use Chinese for user-facing collaboration in this workspace.
- Run commands from the repository root unless a script says otherwise.
- `RUN.bat` is the full Windows build, install, and launch flow. Let it finish
  naturally; do not stop it with a short debug timeout.
- Keep runtime data under the configured user data directory, not in the repo.
- The only remote for this checkout is GitHub `origin`.
- Multi-monitor screenshot capture is intentionally atomic. If any physical
  monitor fails, discarding the whole capture cycle is expected behavior.
- Validate Python packaging dependencies inside `.venv-backend-runtime-gpu`;
  the machine-wide Python environment is shared with unrelated projects.

## Before Changing Code

The working tree may hold more than one unfinished workstream at once, so
establish what is already there before editing or committing:

```powershell
git status
git branch --show-current
git log -8 --oneline
```

Keep unrelated workstreams in separate commits.

## Verification Commands

Run the checks that match what you changed, from the repository root:

```powershell
python -m pytest -q                                  # Python
npm --prefix src/webapp run lint                     # frontend lint
npm --prefix src/webapp test                         # frontend tests
npm --prefix src/webapp run build                    # frontend build
npm --prefix src/webapp run never-stop:test          # Never Stop demo
```

`python -m pytest -q` covers `tests/` only. `npm --prefix src/webapp run check`
runs lint, tests, and build in one step but does not include the Never Stop
suite, so run `never-stop:test` explicitly when that subproject changes.

`npm --prefix src/webapp run dev` is the Vite dev server; it is not a standalone
application, and `RUN_DEV.bat` is the development entry point.

## Subprojects

- `src/webapp/` is the Electron + React desktop app.
- `src/webapp/never-stop/` is a separate Electron entry point for the Never Stop
  demo. It has its own npm scripts (`never-stop:build`, `never-stop:start`,
  `never-stop:test`, `never-stop:package`) and its own version number in
  `src/webapp/never-stop/electron-builder.cjs`, which is independent of the main
  app version in `src/webapp/package.json`. A difference between those two
  versions is expected, not a conflict.
- `src/webapp/never-stop/VALIDATION.md` records per-version delivery evidence for
  that subproject. Keep its entries factual and scoped to what was actually run.

## Source of Truth

When information conflicts, prefer it in this order:

1. Current source code
2. Current tests
3. Current runtime logs and actual endpoints
4. Design documents
5. Implementation plans
6. README and prose documentation

An "already done" claim in a plan or design document is not evidence that the
current branch contains that work. Verify against source and tests first, and do
not restate unverified claims as fact.

## README Badges

- Dynamic status badges must reference real, existing workflows or repository
  metadata.
- Static stack, platform, and version badges must match tracked configuration or
  documentation.
- Update relevant badges whenever dependencies or supported platforms change.
- Remove badges that become broken, stale, or unverifiable.
- Never fabricate passing status, coverage, quality, security, compliance,
  version, download, or support claims.
- Do not add a coverage badge unless the repository has a real coverage
  collector and published reporting source.
