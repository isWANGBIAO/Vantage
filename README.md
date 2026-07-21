# Vantage

<p align="center">
  <a href="https://github.com/isWANGBIAO/Vantage/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush"><img alt="CI status" src="https://img.shields.io/github/actions/workflow/status/isWANGBIAO/Vantage/ci.yml?branch=main&amp;event=push&amp;style=flat-square&amp;label=CI"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/actions/workflows/codeql.yml?query=branch%3Amain"><img alt="CodeQL status" src="https://img.shields.io/github/actions/workflow/status/isWANGBIAO/Vantage/codeql.yml?branch=main&amp;style=flat-square&amp;label=CodeQL"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/isWANGBIAO/Vantage?style=flat-square&amp;label=Release"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/releases"><img alt="Total release downloads" src="https://img.shields.io/github/downloads/isWANGBIAO/Vantage/total?style=flat-square&amp;label=Downloads"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/blob/main/LICENSE"><img alt="Repository license" src="https://img.shields.io/github/license/isWANGBIAO/Vantage?style=flat-square&amp;label=License"></a>
</p>
<p align="center">
  <a href="https://github.com/isWANGBIAO/Vantage#requirements"><img alt="Windows supported" src="https://img.shields.io/badge/Windows-supported-0078D4?style=flat-square&amp;logo=windows&amp;logoColor=white"></a>
  <a href="https://github.com/isWANGBIAO/Vantage#features"><img alt="macOS supported" src="https://img.shields.io/badge/macOS-supported-000000?style=flat-square&amp;logo=apple&amp;logoColor=white"></a>
  <a href="https://github.com/isWANGBIAO/Vantage#requirements"><img alt="Python 3.11" src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white"></a>
  <a href="https://github.com/isWANGBIAO/Vantage#requirements"><img alt="Node.js 22" src="https://img.shields.io/badge/Node.js-22-5FA04E?style=flat-square&amp;logo=nodedotjs&amp;logoColor=white"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/blob/main/requirements.txt"><img alt="FastAPI 0.139.0" src="https://img.shields.io/badge/FastAPI-0.139.0-009688?style=flat-square&amp;logo=fastapi&amp;logoColor=white"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/blob/main/src/webapp/package.json"><img alt="React 19.2.7" src="https://img.shields.io/badge/React-19.2.7-61DAFB?style=flat-square&amp;logo=react&amp;logoColor=black"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/blob/main/src/webapp/package.json"><img alt="Electron 42.6.0" src="https://img.shields.io/badge/Electron-42.6.0-47848F?style=flat-square&amp;logo=electron&amp;logoColor=white"></a>
</p>
<p align="center">
  <a href="https://github.com/isWANGBIAO/Vantage/commits/main"><img alt="Last commit on main" src="https://img.shields.io/github/last-commit/isWANGBIAO/Vantage/main?style=flat-square&amp;label=Last%20Commit"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/graphs/contributors"><img alt="Contributors" src="https://img.shields.io/github/contributors/isWANGBIAO/Vantage?style=flat-square&amp;label=Contributors"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/issues"><img alt="Open issues" src="https://img.shields.io/github/issues/isWANGBIAO/Vantage?style=flat-square&amp;label=Issues"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/pulls"><img alt="Open pull requests" src="https://img.shields.io/github/issues-pr/isWANGBIAO/Vantage?style=flat-square&amp;label=Pull%20Requests"></a>
  <a href="https://github.com/isWANGBIAO/Vantage"><img alt="GitHub stars" src="https://img.shields.io/github/stars/isWANGBIAO/Vantage?style=flat-square&amp;label=Stars"></a>
  <a href="https://github.com/isWANGBIAO/Vantage/network/members"><img alt="GitHub forks" src="https://img.shields.io/github/forks/isWANGBIAO/Vantage?style=flat-square&amp;label=Forks"></a>
</p>

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
- OpenCV YuNet ONNX face-presence detection for camera-facing faces. This is a
  coarse head-pose filter, not eye tracking or gaze estimation.
- Local prompt templates that users can replace privately.
- Optional face parsing model support. Model weights are not distributed in this
  repository; fallback analysis remains available when no model is configured.

## Requirements

- Python 3.11 recommended for local backend packaging; CI also validates Python 3.13.
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
git tag v1.0.59
git push origin v1.0.59
```

The `Release` workflow builds the Windows installer, generates `SHA256SUMS.txt`,
and publishes the assets to the matching GitHub Release. The tag must match the
frontend package version, for example `v1.0.59` for package version `1.0.59`.

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
the providers you use. Never commit real secrets. Voice transcription normally
uses Settings; `VANTAGE_TRANSCRIBE_*` variables provide CLI/subprocess fallback
configuration for local development.

Location is fail-closed: when Vantage cannot obtain a current, trustworthy
device position, AQI reports location unavailable and captured images omit GPS
metadata instead of guessing a city. For a stationary installation, set both
`VANTAGE_STATIC_LATITUDE` and `VANTAGE_STATIC_LONGITUDE` only as an explicit
user-declared fixed-location override; leave both empty for normal device
location handling.

## Optional Model Assets

The required YuNet face detector and its MIT license are tracked under
`src/models/` and bundled with the backend runtime. It runs through OpenCV DNN,
so the installed app does not require PyTorch, Ultralytics, or ONNX Runtime for
camera face-presence detection.

The separate face parsing ONNX model is optional and not bundled in this repository.
Place a licensed model at `src/scripts/models/face_parsing.farl.lapa.int8.onnx`
for local experiments, or run without it and use the fallback path.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

Code in this repository is licensed under the [MIT License](LICENSE). Third-party
models, datasets, and provider APIs may have separate licenses and are not
included unless explicitly documented.
