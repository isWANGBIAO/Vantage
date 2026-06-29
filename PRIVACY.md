# Privacy

Vantage is designed as a local-first desktop application, but it can process
highly sensitive data. Review these rules before running or modifying it.

## Data The App May Handle

- camera frames and saved photos
- screen captures
- optional GPS EXIF metadata when platform location is available
- local health, time, training, project, and finance workbooks
- local logs and generated reports
- LLM prompts, responses, usage records, and provider API keys

## Storage

Packaged Windows builds use `%LOCALAPPDATA%\Vantage` for user data. Packaged
macOS builds use `~/Library/Application Support/Vantage`. Development runs may
use configured runtime directories. Runtime data should not be stored in the
Git repository.

## Network Boundary

The app may call configured LLM, transcription, or model-provider endpoints.
Only configure providers you trust. Do not paste real API keys into source
files; use runtime settings or `.env` files ignored by Git.

## Camera, Screenshots, And Location

Grant camera, screen recording, and location permissions only if you want those
features. Disable or avoid those workflows if you do not want media or location
metadata stored locally.

## Deleting Data

Delete runtime data from the configured Vantage user-data directory. Also check
logs, generated reports, exported spreadsheets, and any manually selected legacy
folders.

## Public Contributions

Never include real personal data in issues, pull requests, screenshots, logs,
test fixtures, or example files. Use synthetic data.
