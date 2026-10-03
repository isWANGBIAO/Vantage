# Persistent model selection and window close Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist the user's model choice and support close-to-tray via Ctrl+W.

**Architecture:** Reuse canonical provider JSON and a narrow backend preference endpoint. Route the window shortcut through the existing close handler.

**Tech Stack:** Python/FastAPI, React, Electron, pytest, Node test runner.

### Task 1: Canonical selection

Files: `src/backend/providers.py`, corresponding provider tests, `src/webapp/src/utils/llmModelCatalog.js`, `src/webapp/src/components/ActionPlan.jsx`, `src/webapp/src/components/ChatInterface.jsx` and corresponding tests.

1. Add failing tests for save/read preference, unrelated provider preservation, invalid model/route and save failure; run the targeted tests and confirm failure.
2. Add a narrow authenticated-by-existing-local-transport preference operation using existing configuration locks/atomic persistence; validate the configured enabled route and model.
3. Persist changes before publishing selection, favor the canonical catalog default over stale browser cache, and ensure both plan/chat callers use the unified helper.
4. Run targeted Python and frontend tests, then full frontend checks. Review no credentials are exposed.

### Task 2: Close shortcut

Files: `src/webapp/main.cjs`, `src/webapp/main.test.js`, optional focused shortcut helper/test.

1. Add a failing behavioral test for Ctrl+W/Command+W closing the window without quitting and unrelated input remaining unaffected.
2. Add the window-local handler, invoking existing close-to-tray behavior.
3. Run targeted and full frontend tests.

### Task 3: Release/install

1. Review diffs and run applicable Python tests, frontend lint/test/build and production UI smoke.
2. Bump main package and lockfile patch version, synchronize README release examples; keep Never Stop unchanged.
3. Commit only scoped changes with detailed explanation; run `RUN.bat` to natural completion.
4. Verify installed executable, installed build metadata, live backend and preserved data. Set canonical preference to the user's configured DeepSeek route using the same new operation, without triggering generation.
