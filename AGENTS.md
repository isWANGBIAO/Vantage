# Repository Agent Notes

This repository is public-facing. Do not commit private prompts, health exports,
screenshots, photos, finance workbooks, local logs, API keys, or machine-specific
paths.

- Use Chinese for user-facing collaboration in this workspace.
- Run commands from the repository root unless a script says otherwise.
- If Python files change, run the relevant Python tests before finishing.
- `RUN.bat` is the full Windows build, install, and launch flow. Let it finish
  naturally; do not stop it with a short debug timeout.
- Keep runtime data under the configured user data directory, not in the repo.
- The only remote for this checkout is GitHub `origin`.
