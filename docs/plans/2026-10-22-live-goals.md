# Live Goals Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve #114 by making saved goal.md the sole execution target.

**Architecture:** A bounded strict goal reader validates execution input. Runner
reads each invocation from disk and records its adopted file hash; Application
saves do not enter interrupting control operations. UI has save/adoption states,
not a draft/publication gate. Legacy API compatibility does not drive start.

**Tech Stack:** Node.js CommonJS, React, node:test and real inert local children.

---

### Task 1: execution boundaries

Files: create `src/webapp/never-stop/core/live-goals.test.cjs` and `goal.cjs`;
modify `runner.cjs`, `application.cjs` and focused existing tests.

1. Add inert recorder regressions for save/start, external edits, held current
   invocation, next turn/reset/restart and invalid input without launch.
2. Run `node --test src/webapp/never-stop/core/live-goals.test.cjs`; observe
   failures against the previous published-snapshot implementation.
3. Implement strict bounded UTF-8 reader and fresh per-invocation goal input.
   Preserve atomic file saves, conflict handling and process ownership.
4. Run focused tests, then the full Never Stop suite and inspect failures.
5. Commit the execution contract with issue/test evidence.

### Task 2: truthful UI and documentation

Files: modify `never-stop/ui/App.jsx`, `state.mjs`, `state.test.mjs`, README.

1. Add failing save/adoption status and UI contract tests.
2. Remove publication gate/button; compare saved and adopted versions and show
   that a running invocation is not interrupted by automatic saving.
3. Update README and historical-contract tests to match saved-file semantics.
4. Run frontend lint, tests, build and explicit `never-stop:test`.
5. Commit and create a draft PR for independent review and required CI.
