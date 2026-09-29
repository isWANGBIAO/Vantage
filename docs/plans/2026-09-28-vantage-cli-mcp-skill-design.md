# Vantage CLI, MCP, Skill and computer-use Integration Design

## Status

Approved by the user on 2026-09-28. The user explicitly does not want a built-in
AI agent. The goal is a unified command-line interface, MCP server, and project
Skill that let compatible assistants and computer-use workflows operate the
full Vantage product without reimplementing its business rules.

## Current source facts

- Vantage is a React/Electron desktop application backed by a local FastAPI
  server. The backend defaults to `127.0.0.1:8000` and already owns most
  product operations through `/api/*` routes.
- The frontend calls those backend routes directly, while Electron IPC owns a
  smaller set of native-app concerns such as settings persistence, onboarding,
  opening configured data directories, title-bar theme, and login-at-startup.
- `src/core/user_config.py` already sanitizes and persists shared settings and
  provider JSON. Runtime files belong in the configured user-data directory.
- Python command-line scripts in `src/scripts/` currently cover maintenance,
  packaging, or single-purpose analysis; there is no single product CLI or MCP
  server.
- The repository includes checks for Python, frontend, packaging, runtime
  lifecycle, and desktop IPC behavior. Those are the compatibility boundary
  for adding automation entry points.

## Goals

1. Provide one `vantage` command with discoverable subcommands and text/JSON
   output for the user-facing product capabilities.
2. Provide a local MCP server whose tools and resources are derived from the
   same operation definitions as the CLI.
3. Make each current user-facing operation reachable through at least one
   stable CLI command and one MCP tool, including settings operations currently
   exposed only through Electron IPC.
4. Package the command and MCP entry point with the Windows application so the
   user does not need a second Python installation.
5. Add a project Skill that tells compatible assistants when to use MCP, CLI,
   or visible computer use, and documents complete end-to-end workflows.
6. Maintain a source-grounded project memory document inside Vantage, separate
   from `AGENTS.md`, for the Skill and model handoffs to reference.
7. Let computer-use workflows complete product tasks by preferring CLI/MCP for
   reliable actions and retaining the Electron UI for visual inspection and
   native interactions.

## Non-goals

- Do not create a Vantage-hosted autonomous agent or model orchestration loop.
- Do not duplicate calculations, provider logic, settings validation, or data
  mutation rules in the CLI or MCP layer.
- Do not expose internal-only endpoints such as renderer camera frame transport
  as product tools unless a user-facing workflow requires them.
- Do not place private prompts, workbook contents, photos, logs, API keys, or
  machine-specific paths in tracked project memory or examples.

## Architecture decision

### One operation catalog

Create a typed operation catalog in the Python backend. Each operation records
its stable name, description, input schema, output kind, and the canonical
backend route or shared configuration operation it invokes. A single
`VantageClient` handles backend readiness, requests, JSON/text rendering,
streamed responses, and file downloads. The CLI dispatcher and MCP registration
consume this catalog rather than defining independent tools.

The FastAPI routes and shared configuration services remain the business-logic
source. Where a desktop-only product operation has no backend/API equivalent,
add a backend operation that uses the existing service or configuration code;
adapt Electron IPC and the frontend to call that same operation where practical.
Native OS effects that must run inside Electron remain a narrow bridge, not a
second implementation of product rules.

### CLI

- Provide `python -m src.cli` for repository development and a packaged
  `vantage` command for installed Windows builds.
- Use Python's standard `argparse` unless a concrete feature requires an
  additional CLI dependency.
- Group commands by user-facing product area: system/status, settings/providers,
  models, chat/context, action plans, plots, finance, face history, sedentary
  health, project progress, usage, logs, and data paths.
- Support `--format text|json`; streams and generated files use explicit
  stdout/file destinations with stable exit codes and useful errors.
- Reuse the existing packaged backend and runtime directories. Do not create a
  second copy of the Python runtime or place data in the repository.

### MCP

- Provide `vantage mcp` using the official Python MCP SDK.
- Default to stdio for local desktop hosts. Add Streamable HTTP only if a
  verified use case requires a long-running network listener.
- Register tools and resources from the operation catalog. Tool descriptions
  and argument schemas come from the same definitions used by CLI help.
- Keep protocol logs on stderr so stdout remains valid MCP transport data.
- The MCP process reuses the backend if it is already running and gives a clear
  startup error otherwise; any optional auto-start must use the existing
  packaged backend lifecycle and health check rather than inventing a second
  server process model.

### Skill and computer use

- Add `.agents/skills/vantage/SKILL.md` as the assistant-facing entry point.
- Add `docs/vantage-project-memory.md` as the source-grounded architecture and
  workflow reference. It is not a replacement for current source/tests and is
  not stored in `AGENTS.md`.
- Include a product-operation parity table mapping UI capability, canonical
  operation, CLI command, and MCP tool/resource.
- For computer-use tasks, the Skill directs assistants to perform reliable
  reads and mutations through MCP/CLI, then use the desktop UI for visual-only
  work and verify resulting state through the canonical operation.

## Product operation coverage

The implementation inventory must be checked against current UI calls,
`@app` routes, and Electron IPC. At minimum, cover:

| Product area | Existing source boundary | Required automation capability |
| --- | --- | --- |
| System | `/api/status`, `/api/sys_stats`, `/api/health/sedentary` | Read status/stats/sedentary state |
| Planning | `/api/action_plan/*`, `/api/chat/context`, `/api/chat` | Read, generate, stream, and verify complete plans; read/reset chat context |
| Models/settings | `/api/llm_models*`, `/api/provider_models/discover`, Electron `settings:*` | Read/update shared JSON settings and provider/model configuration; discover models |
| Plots | `/api/plots/*` | Refresh and read dashboard plots |
| Finance | `/api/balance_sheet*` | Read sheet/recommendations; regenerate, dismiss, and restore recommendations |
| Face history | `/api/face/*` | Read report/progress/live state; start analysis; export results |
| Personal data | `/api/aqi`, `/api/latest_images`, `/api/transcribe`, `/api/project_progress` | Read/calculate current data and use transcription/project workflows |
| Usage and diagnostics | `/api/usage`, `/api/system_logs`, runtime directories | Read usage/logs and open or identify configured paths |
| Desktop-only actions | onboarding, open-path, theme, login-at-startup IPC | Expose a CLI/MCP route or a tested narrow Electron bridge for each user-facing action |

Internal streaming/media plumbing is not automatically a product operation;
the inventory must prove every visible workflow has an equivalent, not expose
private implementation endpoints wholesale.

## Alternatives considered

1. **Thin unified clients over the existing backend (chosen).** CLI, MCP, and
   computer-use guidance share one operation catalog and API/config client.
   This preserves existing Vantage behavior and keeps feature logic in one
   place. It requires a running backend, so backend readiness is explicit and
   should reuse the existing packaged lifecycle.
2. **Independent in-process CLI/MCP implementation.** This can operate without
   the HTTP server but would duplicate startup state, data handling, and domain
   rules across Electron, FastAPI, CLI, and MCP. It is rejected unless a future
   use case proves the backend boundary insufficient.

## Compatibility and validation

- Keep Python support aligned with repository policy: Python 3.11 is the
  packaging recommendation and Python 3.13 is already exercised by CI.
- Pin the MCP SDK in the backend runtime requirements and test the selected
  transport against a real MCP client/inspector before packaging.
- Test shared operation schemas, CLI parsing/output/exit codes, MCP tool/resource
  listing and calls, API parity, settings round trips, backend unavailable and
  streaming/download cases.
- Run `python -m pytest -q`, `npm --prefix src/webapp run lint`,
  `npm --prefix src/webapp test`, `npm --prefix src/webapp run build`, and the
  packaging/runtime checks relevant to changed files. Run `RUN.bat` only for a
  full delivery verification and let it finish naturally.
- Verify CLI/MCP/Skill/package paths against both source development and the
  installed Windows layout; do not claim install support based only on unit
  tests.
