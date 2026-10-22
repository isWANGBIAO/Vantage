# Camera preview live-state repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the stale connecting overlay from a decoded, updating MJPEG preview while retaining error recovery and privacy cleanup.

**Architecture:** Treat positive decoded image dimensions as valid preview evidence even when `img.complete` is true. A completed image without usable dimensions is still a failure; explicit image errors retain bounded retries. Do not use device-online status as proof of visible video or claim to detect every graceful stream EOF from DOM attributes.

**Tech Stack:** React, Electron42, Node tests and the existing isolated production UI smoke.

## Task 1: Reproduce and repair

1. In `src/webapp/src/utils/cameraPreviewLifecycle.test.js`, add a regression for repeated3840x2160 decoded observations with `complete:true`, requiring live state and no retry. Correct the old test's assumption that every completed image is broken; separately retain completed-without-pixels failure assertions. Run the focused test and require the expected failure before changing production code.
2. In `src/webapp/scripts/smoke-unified-ui.cjs`, add a synthetic4K MJPEG case without per-part Content-Length, matching the real backend. Verify it becomes and stays live without the recovery overlay or retry churn. Preserve the existing real TCP interruption, bounded retry and privacy-hide cases; exercise real disconnection after the new case too.
3. In `src/webapp/src/utils/cameraPreviewLifecycle.js`, check usable dimensions before the completed-without-pixels failure branch. Keep onError, attempt/session guards and retry limits unchanged. Run focused tests and actual Electron smoke.

## Task 2: Verify and install

1. Run frontend lint/tests/build, Never Stop tests, production protocol/UI smokes and relevant packaging tests. Obtain independent review; fix any substantive findings before installation.
2. Prepare a patch release using the existing version tool, verify release metadata, and make a detailed local commit. Do not push or merge remotely without the user's request for this fix.
3. Run `RUN.bat` naturally to completion for real backend/CLI/MCP verification, packaging, overwrite installation and launch. Verify installed build metadata, archive/backend identity, healthy service, unchanged settings and clean source state. Use an isolated local Electron diagnostic to check the real video stream's decoded dimensions and lifecycle state without saving or emitting private pixels.
