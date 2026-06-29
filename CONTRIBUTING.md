# Contributing

## Development Setup

Run commands from the repository root.

```powershell
python -m pytest -q
npm --prefix src/webapp test
npm --prefix src/webapp run build
```

For a full Windows packaging, install, and launch check, run:

```powershell
.\RUN.bat
```

Let `RUN.bat` finish naturally.

## Pull Request Checklist

- Do not commit private prompts, `.env`, API keys, logs, screenshots, photos,
  health exports, finance workbooks, or local runtime data.
- Use synthetic fixtures for tests.
- Run relevant Python tests after changing Python files.
- Run frontend tests after changing `src/webapp`.
- Document privacy-sensitive behavior changes in `PRIVACY.md` or `README.md`.

## Optional Model Assets

Face parsing model files are optional runtime assets. Do not commit model
weights unless their source and redistribution license are documented.
