# Vantage Web App

This directory contains the React and Electron frontend for Vantage.

## Commands

```powershell
npm ci
npm test
npm run build
npm run electron:build
```

Run commands from `src/webapp` unless using the repository-level scripts.

## Notes

- The frontend talks to the local FastAPI backend.
- Runtime settings and API keys must stay in user configuration, not source.
- Packaged builds include the backend runtime produced by the root build scripts.
