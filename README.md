# Vantage

Vantage is a local-first desktop workspace for personal analytics. It combines a
Python/FastAPI backend with a React/Electron frontend for time logs, planning,
LLM-assisted summaries, optional media capture, and health-style visualizations.

This public repository intentionally contains only source code, tests, and
synthetic prompt templates. Do not commit private prompts, workbooks, health
exports, finance data, photos, screenshots, logs, or API keys.

## Privacy First

Vantage can process sensitive local data:

- camera frames and saved photos
- screenshots
- optional GPS EXIF metadata
- time, health, project, and finance workbooks
- LLM prompts, responses, usage logs, and provider API keys

Read [PRIVACY.md](PRIVACY.md) before running the app. Runtime data belongs in
the platform user-data directory, not in this repository.

## Features

- Windows and macOS desktop packaging through Electron.
- FastAPI backend for data loading, plotting, chat, action plans, usage logs,
  face-analysis reports, and local media endpoints.
- React UI for dashboard, action plan, chat, plots, usage, settings, expenses,
  project progress, and face-history views.
- Local prompt templates that users can replace privately.
- Optional face parsing model support. Model weights are not distributed in this
  repository; fallback analysis remains available when no model is configured.

## Requirements

- Python 3.12 recommended.
- Node.js 22 recommended for the frontend.
- Windows is the primary packaging target. macOS scripts are included for source
  and packaged workflows.

## Development

Run commands from the repository root.

```powershell
python -m pytest -q
npm --prefix src/webapp test
npm --prefix src/webapp run build
```

Start the source development workflow:

```powershell
.\RUN_DEV.bat
```

macOS:

```bash
./RUN_DEV.sh
```

## Packaging

Windows full build, install, and launch:

```powershell
.\RUN.bat
```

Let `RUN.bat` finish naturally. The installer output is under
`src/webapp/electron-dist`.

Build a Windows release installer without installing or launching the app:

```powershell
.\scripts\build-release-installer.ps1
```

GitHub Releases are automated for version tags. Keep
`src/webapp/package.json` at the release version, tag the commit, and push the
tag:

```powershell
git tag v1.0.58
git push origin v1.0.58
```

The `Release` workflow builds the Windows installer, generates `SHA256SUMS.txt`,
and publishes the assets to the matching GitHub Release. The tag must match the
frontend package version, for example `v1.0.58` for package version `1.0.58`.

macOS full build, install, and launch:

```bash
./RUN.sh
```

## Runtime Directories

Packaged Windows builds use:

- `%LOCALAPPDATA%\Vantage`
- `%LOCALAPPDATA%\Vantage\config`
- `%LOCALAPPDATA%\Vantage\history`
- `%LOCALAPPDATA%\Vantage\logs`
- `%LOCALAPPDATA%\Vantage\plot_outputs`

Packaged macOS builds use:

- `~/Library/Application Support/Vantage`
- `~/Library/Application Support/Vantage/config`
- `~/Library/Application Support/Vantage/history`
- `~/Library/Application Support/Vantage/logs`
- `~/Library/Application Support/Vantage/plot_outputs`

## Configuration

Copy [.env.example](.env.example) to `.env` for local development and fill only
the providers you use. Never commit real secrets.

## Optional Model Assets

The face parsing ONNX model is optional and not bundled in this repository.
Place a licensed model at `src/scripts/models/face_parsing.farl.lapa.int8.onnx`
for local experiments, or run without it and use the fallback path.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party
models, datasets, and provider APIs may have separate licenses and are not
included unless explicitly documented.
