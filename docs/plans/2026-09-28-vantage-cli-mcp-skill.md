# Vantage CLI, MCP and Skill Implementation Plan

> **For Codex:** Use superpowers:subagent-driven-development for independent implementation tasks and test-driven-development for every behavior change.

**Goal:** Expose every user-facing Vantage operation through one packaged CLI/MCP catalog and a tested Skill that enables computer-use workflows without an embedded agent or duplicate domain logic.

**Architecture:** FastAPI and existing configuration services remain authoritative. A Python operation catalog and `VantageClient` provide the common boundary; CLI, MCP, Skill, and parity tests consume it. Electron retains native OS effects, while settings/onboarding are bridged to the same backend operations where necessary.

**Tech Stack:** Python 3.11/3.13, FastAPI, `argparse`, official Python MCP SDK, Electron/React, pytest, Node's built-in test runner, PyInstaller, electron-builder.

---

### Task 1: Inventory product operations and add the catalog

**Files:** Create `src/services/automation_catalog.py`, `tests/test_automation_catalog.py`; inspect `src/server.py`, `src/webapp/src`, and `src/webapp/main.cjs`.

1. Write failing tests for unique stable operation names, schemas, output kinds, and source/UI coverage. Exclude internal camera-frame transport and renderer-only plumbing.
2. Run `python -m pytest tests/test_automation_catalog.py -q`; expect failure because the catalog is missing.
3. Define immutable descriptors for system/status, settings/providers, models, chat/context, action plans, plots, finance, face history, sedentary, project progress, usage, logs, media/transcription, and native path/onboarding actions. Each descriptor includes method/path or shared-config handler, input schema, output kind, and side-effect/stream/download metadata.
4. Re-run the focused test; expect all catalog assertions to pass against current routes, frontend calls, and IPC.
5. Commit with detailed message `feat(automation): define shared Vantage operation catalog`.

### Task 2: Implement the shared backend client

**Files:** Create `src/services/vantage_client.py`, `tests/test_vantage_client.py`.

1. Write failing tests for JSON calls, schema validation, backend-down/HTTP errors, NDJSON streams, file downloads, multipart audio uploads (`file_path` maps to the API's `file` field), required local action-intent headers, and explicit errors for catalog operations whose Electron/backend bridge is not yet available.
2. Run `python -m pytest tests/test_vantage_client.py -q`; expect failure because the client is missing.
3. Implement a typed client that dispatches catalog entries, resolves the configured loopback URL, and handles requests, streaming, and file results without copying business logic.
4. Re-run the focused test; expect all behaviors to pass.
5. Commit with detailed message `feat(automation): add shared backend client`.

### Task 3: Unify settings and other desktop-only operations

**Files:** Modify `src/server.py`, `src/core/user_config.py` only as needed, `src/webapp/main.cjs`; add `tests/test_settings_automation_endpoint.py` and extend `src/webapp/main.test.js`.

1. Write failing parity tests for settings/provider JSON read-update round trips, onboarding state, allowed paths, and preservation of Electron login-item/tray/theme effects.
2. Run `python -m pytest tests/test_settings_automation_endpoint.py -q` and `npm --prefix src/webapp test -- main.test.js`; expect missing API/parity failures.
3. Add loopback-only backend operations using existing sanitizers/persistence. Route Electron settings persistence through the canonical operation; keep only OS-native side effects in the Electron bridge.
4. Re-run focused tests; expect API and desktop state to remain compatible.
5. Commit with detailed message `feat(settings): expose shared local automation operations`.

### Task 4: Implement the catalog-driven product CLI

**Files:** Create `src/cli.py`, `tests/test_cli.py`; modify `src/scripts/run_server_background.py` for packaged dispatch if required.

1. Write failing tests for help, catalog-derived command groups/options, `--format text|json`, streaming, file output, exit codes, and actionable backend-unavailable errors.
2. Run `python -m pytest tests/test_cli.py -q`; expect failure because the unified CLI is missing.
3. Use built-in `argparse` and `VantageClient`; provide `python -m src.cli` for source runs and a CLI mode in the existing packaged backend (no second Python runtime). Include every user-facing operation from the catalog.
4. Re-run focused tests; expect complete command discovery and dispatch.
5. Commit with detailed message `feat(cli): add catalog-driven Vantage command line`.

### Task 5: Implement MCP from the same operation catalog

**Files:** Create `src/mcp_server.py`, `tests/test_mcp_server.py`; update `requirements-core.txt` and runtime resources only as needed.

1. Write failing in-memory MCP client tests for listed tools/resources, schemas/descriptions matching the catalog, representative calls/errors, and stdio cleanliness.
2. Run `python -m pytest tests/test_mcp_server.py -q`; expect failure because the server/dependency is missing.
3. Pin the verified official SDK, register tools/resources from catalog definitions, default to stdio, and send diagnostics only to stderr. Reuse a ready backend and return an actionable error if unavailable. Do not add an agent loop.
4. Re-run MCP tests and an official inspector/client round trip; expect protocol and operation calls to pass.
5. Commit with detailed message `feat(mcp): expose shared Vantage operations over stdio`.

### Task 6: Package the installed `vantage` command

**Files:** Modify `src/core/backend_runtime_packaging.py`, `src/scripts/run_server_background.py`, `src/webapp/package.json`, `RUN.bat`, and relevant Python/Node packaging tests.

1. Add failing layout tests proving the Windows installer includes the command entry, MCP SDK/resources, and correct packaged user-data paths without a duplicate runtime.
2. Run affected packaging tests; expect failure because the command entry is absent.
3. Add an installed `vantage` launcher that dispatches CLI/MCP modes through the existing bundled backend, never opens the Electron window, preserves MCP stdio, and keeps the existing health/lifecycle behavior.
4. Re-run packaging tests and the built-backend verifier; expect command discovery and MCP startup checks to pass.
5. Commit with detailed message `build(cli): package Vantage command and MCP entry point`.

### Task 7: Create Vantage project memory and Skill

**Files:** Create `docs/vantage-project-memory.md`, `.agents/skills/vantage/SKILL.md`, and `tests/test_vantage_skill.py`.

1. Before writing the Skill, have a subagent attempt three retrieval/application tasks without it: find an operation, update and verify a setting, and perform a plan workflow using CLI/MCP/computer use. Record missing/invented paths.
2. Write failing tests for Skill metadata, command/tool names, parity references, project source-truth guidance, and the memory file being in Vantage rather than `AGENTS.md`.
3. Run `python -m pytest tests/test_vantage_skill.py -q`; expect failure because the docs are missing.
4. Write concise source-grounded project memory from current source/tests, then a Skill that routes actions to CLI/MCP and visual inspection to computer use. Exclude private prompts, data, logs, secrets, and machine paths.
5. Re-run the same scenarios with the Skill. Fix only observed retrieval gaps and re-test.
6. Commit with detailed message `docs(skill): add Vantage operation memory and assistant guide`.

### Task 8: Enforce full operation parity

**Files:** Create `tests/test_automation_parity.py`; update catalog, API, frontend, Skill only for demonstrated gaps.

1. Write a parity test comparing the catalog with public FastAPI routes, frontend backend calls, and user-facing Electron IPC. Require CLI and MCP coverage plus a Skill reference for each supported operation.
2. Run `python -m pytest tests/test_automation_parity.py -q`; expect failure on uncovered operations.
3. Add only missing adapters or bridge operations; keep internal-only transport details out of the public catalog.
4. Re-run parity plus adjacent CLI/MCP/desktop tests; expect every user-facing operation to be covered.
5. Commit with detailed message `test(automation): enforce UI CLI MCP operation parity`.

### Task 9: Validate and document the complete delivery

**Files:** Update `README.md` and command/MCP docs as required.

1. Run `python -m pytest -q`, `npm --prefix src/webapp run lint`, `npm --prefix src/webapp test`, and `npm --prefix src/webapp run build`.
2. Verify built/installed `vantage --help`, a read, a state-changing operation, and an MCP client round-trip. Run `RUN.bat` only for delivery verification and let it finish naturally.
3. Check `git diff --check`, status, commit list, operation parity, and that no private data/secrets were staged. Report any unverified operation rather than claiming complete coverage.
4. If README-only changes remain, commit with detailed message `docs(cli): document Vantage CLI and MCP usage`.
