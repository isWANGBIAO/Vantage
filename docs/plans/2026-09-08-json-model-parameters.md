# JSON Model Parameters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move Vantage's default and model-specific LLM sampling/reasoning parameters into the persisted provider JSON configuration and apply the verified profiles at request time.

**Architecture:** `providers.json` will carry a validated `sampling_defaults` object and `model_profiles` map. The Python backend will sanitize and consume these values, while the Electron-side JSON sanitizer will preserve the same schema so onboarding/settings writes cannot erase them. Model matching will support exact IDs and trailing-`*` prefixes.

**Tech Stack:** Python, unittest, JavaScript JSON sanitizer, provider OpenAI-compatible Chat Completions.

---

### Task 1: Lock the JSON contract with failing tests

**Files:**
- Modify: `tests/test_user_config.py`
- Modify: `tests/test_llm_client.py`

**Steps:**
1. Add tests requiring default sampling values and Qwen/DeepSeek/GLM profile overrides to survive provider-config sanitization.
2. Add request-payload tests proving the configured default and profile values reach the outgoing request.
3. Run the focused tests and confirm they fail because the JSON contract is not implemented.

### Task 2: Implement backend JSON configuration and request application

**Files:**
- Modify: `src/core/user_config.py`
- Modify: `src/services/llm_client.py`

**Steps:**
1. Add validated defaults and model-profile sanitization to `providers.json`.
2. Expose the sanitized parameter configuration to `LLMClient`.
3. Build the base request sampling fields from JSON instead of hard-coded `0.6/0.7/0.5` values.
4. Apply exact/prefix model profiles, including omitted parameters and thinking payloads.
5. Keep backward compatibility when an older providers file has no parameter section.
6. Run the focused tests and confirm they pass.

### Task 3: Preserve the schema in the desktop JSON sanitizer

**Files:**
- Modify: `src/webapp/src/utils/onboardingConfig.cjs`
- Modify: `src/webapp/src/utils/onboardingConfig.test.js`

**Steps:**
1. Add the same defaults and profile-preservation behavior to the Electron-side sanitizer.
2. Add a regression test proving onboarding save/load does not drop model parameters.
3. Run the relevant JavaScript tests.

### Task 4: Verify current live providers and repository state

**Steps:**
1. Run the backend focused suite and the full Python test suite relevant to changed modules.
2. Validate the effective JSON shape without printing API keys.
3. Recheck live `/models` status for enabled providers and record that the Qwen3.8 endpoint currently returns 502 if it remains unavailable.
4. Review the diff and report exact behavior, evidence, and any remaining runtime blocker.
