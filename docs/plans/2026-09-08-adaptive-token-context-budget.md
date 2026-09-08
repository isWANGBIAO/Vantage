# Adaptive Token Context Budget Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace route-specific Time.xlsx row limits with one provider/model-aware token budget that automatically selects as much usable context as fits for every route.

**Architecture:** Build the prompt in two phases. First assemble fixed prompt sections and resolve a conservative input-token budget from provider/model metadata, configured defaults, and an output reserve. Then select Time.xlsx and Balance Sheet rows by priority using token estimates, emitting explicit inclusion and omission metadata. Keep one bounded retry path for context-limit failures.

**Tech Stack:** Python, pandas, JSON, OpenAI-compatible provider metadata, pytest/unittest, existing action-plan statistics and Electron UI.

---

## Design decisions

1. Remove the SJTU-specific 14-day and 8-row rules. The route must not determine a different data policy.
2. Keep the current 250,000-token proxy ceiling only as a global safety fallback, not as a row count.
3. Resolve the usable input budget as `min(global_ceiling, provider_model_context_window) - output_reserve - protocol_overhead`. If the provider does not advertise a context window, use the global fallback and record that fact.
4. Use a model tokenizer when available; otherwise use the existing conservative character estimator and record `estimator=fallback_chars`.
5. Select rows by priority: required metadata, today/latest row, future plans, newest history, then older history. Rows are never split.
6. Include `budget_tokens`, `estimated_tokens`, `included_row_count`, `omitted_row_count`, date range, estimator, and selection strategy in the JSON payload.
7. If fallback providers are possible, budget against the smallest known context window in the candidate chain.

## Task 1: Add shared token-budget utilities

**Files:**
- Create: `src/utils/prompt_budget.py`
- Test: `tests/test_prompt_budget.py`

**Steps:**

1. Write failing tests for mixed-language token estimation, deterministic row selection, priority ordering, exact budget compliance, and omission metadata.
2. Run `python -m pytest tests/test_prompt_budget.py -q`; expect failure because the module does not exist.
3. Implement pure functions that resolve a budget, estimate serialized token cost, and select structured rows without knowing provider names.
4. Rerun the focused tests; expect all to pass.
5. Commit with `git add src/utils/prompt_budget.py tests/test_prompt_budget.py` and `git commit -m "Add adaptive prompt token budget utilities"`.

## Task 2: Make DataLoader token-bound

**Files:**
- Modify: `src/utils/data_loader.py:553-720`
- Test: `tests/test_data_loader.py`

**Steps:**

1. Add failing tests for a small explicit budget, priority retention, deterministic output, truncation metadata, and route-independent selection.
2. Run `python -m pytest tests/test_data_loader.py -q`; expect failures for the new fields and behavior.
3. Refactor `construct_prompt` into two phases: load candidates and fixed sections, calculate remaining budget, select rows, then serialize one bounded Time Series section. Future plans must be included in the same budget accounting instead of appended without a bound.
4. Preserve legacy `days` and `start_date` compatibility, but remove route-specific branches from DataLoader.
5. Rerun `python -m pytest tests/test_data_loader.py -q`; expect all to pass.
6. Commit with `git add src/utils/data_loader.py tests/test_data_loader.py` and `git commit -m "Bound Time.xlsx context by token budget"`.

## Task 3: Resolve provider/model limits uniformly

**Files:**
- Modify: `src/core/user_config.py`
- Modify: `src/services/llm_client.py`
- Modify: `src/scripts/run_prompt.py`
- Test: `tests/test_user_config.py`
- Test: `tests/test_llm_client.py`
- Test: `tests/test_run_prompt.py`

**Steps:**

1. Add failing tests for optional `context_window_tokens` and `max_output_tokens`, model-discovery fields such as `context_length`, smallest-limit selection across fallback providers, and identical SJTU/non-SJTU budget flow.
2. Run `python -m pytest tests/test_user_config.py tests/test_llm_client.py tests/test_run_prompt.py -q`; expect failures.
3. Add optional provider/model metadata and one LLM-client resolver returning context window, output reserve, usable budget, source, and candidate routes/models. Read common fields without requiring them.
4. Make `run_prompt.py` call this resolver before `DataLoader.construct_prompt`. Remove `ACTION_PLAN_SJTU_TIME_SERIES_DAYS` and the SJTU-specific Balance Sheet limit.
5. Rerun the focused suite; expect all to pass.
6. Commit with `git add src/core/user_config.py src/services/llm_client.py src/scripts/run_prompt.py tests/test_user_config.py tests/test_llm_client.py tests/test_run_prompt.py` and `git commit -m "Resolve prompt budgets across all provider routes"`.

## Task 4: Add bounded retry and diagnostics

**Files:**
- Modify: `src/scripts/run_prompt.py`
- Modify: `src/services/model_call_recorder.py`
- Modify: `src/webapp/src/utils/actionPlanStats.js`
- Modify: `src/webapp/src/components/ActionPlan.jsx`
- Test: `tests/test_run_prompt.py`
- Test: `tests/test_model_call_recorder.py`
- Test: `src/webapp/src/utils/actionPlanStats.test.js`
- Test: `src/webapp/src/components/ActionPlan.test.js`

**Steps:**

1. Add failing tests for `prompt_budget_tokens`, `estimated_prompt_tokens`, estimator, included/omitted Time rows, budget source, and one retry after a recognized context-limit or empty-response failure.
2. Implement one smaller-budget rebuild retry; do not retry arbitrary provider errors or loop indefinitely.
3. Show budget and omitted-row information in Action Plan diagnostics instead of implying all workbook rows were sent.
4. Run the focused Python and frontend tests; expect all to pass.
5. Commit the diagnostics changes with `git commit -m "Expose adaptive prompt truncation diagnostics"`.

## Task 5: Full verification and cleanup

**Files:**
- Modify: `docs/` only if behavior documentation needs updating

**Steps:**

1. Run `python -m pytest tests/test_data_loader.py tests/test_run_prompt.py tests/test_llm_client.py tests/test_user_config.py tests/test_model_call_recorder.py -q`.
2. Run the documented frontend test command and `npm run build` from `src/webapp`.
3. Build identical fixture prompts for all configured routes and confirm route names do not alter selection; only real provider/model budget metadata may differ.
4. Confirm no API keys, private prompts, local paths, logs, or workbook data are committed, and the old SJTU constants are gone.
5. Run `git status --short` and `git diff --check`; commit only documentation or verification changes if any.

