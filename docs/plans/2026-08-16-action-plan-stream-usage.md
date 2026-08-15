# Action Plan Stream Usage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Request streamed token usage when supported and make Action Plan distinguish a normally completed reply with unavailable usage from a genuinely incomplete model stream.

**Architecture:** The LLM transport requests `stream_options.include_usage`, retries the same provider once without that option only when the provider explicitly rejects it, and returns terminal metadata after the existing stream validation succeeds. The Action Plan backend preserves missing usage as unknown and saves terminal metadata per round; the frontend classifies each round into incomplete, usage unavailable, or no notice.

**Tech Stack:** Python 3.11, `requests`, FastAPI subprocess flow, React, Node test runner, CSS, pytest.

---

### Task 1: Request streaming usage and return terminal evidence

**Files:**
- Modify: `tests/test_llm_client.py`
- Modify: `src/services/llm_client.py:762-833,912-923,1156-1351`

**Step 1: Write the failing streamed-usage test**

Add a successful fake SSE response with a content chunk, a `stop` chunk, a
final dictionary-shaped usage chunk, and `[DONE]`. Assert that the outgoing
payload contains:

```python
{"stream_options": {"include_usage": True}}
```

Assert that the result contains the returned usage plus:

```python
{
    "stream_completed": True,
    "stream_terminal_event": "done",
    "finish_reason": "stop",
}
```

Include an intermediate `"usage": null` chunk so the test proves null events
do not erase final usage.

**Step 2: Run the new test and verify RED**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_llm_client.py -k "requests_stream_usage" -q
```

Expected: FAIL because the request lacks `stream_options` and the result lacks
terminal metadata.

**Step 3: Implement the minimal streamed-usage and terminal fields**

When `stream` is true, add the stream option to the base payload. In the SSE
loop, only replace `usage_data` when `data.get("usage")` is a dictionary. After
the existing abnormal/missing terminal checks pass, select the last normalized
finish reason and add the three terminal fields to the returned result.

**Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again.

Expected: PASS.

**Step 5: Write the failing compatibility-fallback test**

Configure the first fake POST response to raise an HTTP 400 whose response body
explicitly names unsupported `stream_options`. Configure the second response
as successful. Assert two calls target the same provider and model, the first
payload contains `stream_options`, and the second does not.

**Step 6: Run the fallback test and verify RED**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_llm_client.py -k "retries_without_unsupported_stream_options" -q
```

Expected: FAIL because `_post_with_failover` currently moves on after the
client error.

**Step 7: Implement one compatibility retry**

Add a narrowly scoped predicate that requires status 400, 404, or 422, the
literal field name `stream_options`, and an unsupported/unknown/extra-field
marker in the response. When it matches and the provider payload contains the
field, remove only that field and retry the same provider/model once. Keep all
other request errors on the existing retry/failover path.

**Step 8: Verify Task 1**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_llm_client.py -q
```

Expected: all LLM client tests pass, including the existing missing-terminal
and `finish_reason=length` failures.

**Step 9: Commit**

```powershell
git add src/services/llm_client.py tests/test_llm_client.py
git commit -m "fix: capture streamed usage and terminal status" -m "Request final usage from OpenAI-compatible streams, retry the same provider without unsupported stream options, retain dictionary-shaped usage events, and expose validated terminal metadata without weakening incomplete-stream rejection."
```

### Task 2: Preserve unavailable usage in Action Plan statistics

**Files:**
- Modify: `tests/test_run_prompt.py`
- Modify: `src/scripts/run_prompt.py:111-148,212-279,323-386`

**Step 1: Write the failing missing-usage aggregation test**

Add a fake client that returns non-empty content, `usage: {}`, a positive
duration, and successful stream terminal metadata. Run one Action Plan round
and assert:

```python
self.assertEqual(result["usage"], {})
```

**Step 2: Run it and verify RED**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_run_prompt.py -k "preserves_missing_usage" -q
```

Expected: FAIL because retry aggregation currently replaces missing usage with
explicit zero totals.

**Step 3: Preserve whether usage was actually recorded**

Introduce one helper that recognizes usage only when at least one token,
cache, or reasoning count is positive. Track that boolean separately from the
numeric retry totals. Return the numeric totals only when usage was recorded;
otherwise keep `usage` as `{}`.

**Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again.

Expected: PASS.

**Step 5: Write failing statistics tests**

Cover these contracts in `build_action_plan_request_stats`:

```python
# Successful stream with no usage
stats["usage_recorded"] is False
stats["prompt_tokens"] is None
stats["stream_completed"] is True
stats["stream_terminal_event"] == "done"
stats["finish_reason"] == "stop"

# Current local-server usage shape
result["usage"]["reasoning_tokens"] == 7
stats["completion_reasoning_tokens"] == 7
```

Also cover explicit zero-only usage as unrecorded.

**Step 6: Run the new statistics tests and verify RED**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_run_prompt.py -k "stream_metadata or reasoning_tokens or zero_usage" -q
```

Expected: FAIL because terminal fields and top-level reasoning normalization do
not yet exist, and explicit zeros are currently called recorded usage.

**Step 7: Save terminal fields and normalize local reasoning usage**

Reuse the recorded-usage helper in `build_action_plan_request_stats`. Normalize
top-level `reasoning_tokens` after the existing canonical and nested forms.
Add `stream_completed`, `stream_terminal_event`, and `finish_reason` from the
LLM result to each request-stat object.

**Step 8: Verify Task 2**

Run:

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_run_prompt.py -q
```

Expected: all Action Plan script tests pass.

**Step 9: Commit**

```powershell
git add src/scripts/run_prompt.py tests/test_run_prompt.py
git commit -m "fix: preserve Action Plan usage availability" -m "Keep absent stream usage unknown instead of synthesizing zero totals, normalize the local reasoning-token field, and persist validated terminal metadata in each saved Action Plan round."
```

### Task 3: Render separate usage and incomplete notices

**Files:**
- Modify: `src/webapp/src/utils/actionPlanStats.test.js`
- Modify: `src/webapp/src/utils/actionPlanStats.js:155-316`
- Modify: `src/webapp/src/components/ActionPlan.test.js`
- Modify: `src/webapp/src/components/ActionPlan.jsx:20-32,833-847,1118-1126,1177-1185`
- Modify: `src/webapp/src/utils/displayCopy.js:153,750`
- Modify: `src/webapp/src/App.css:266-274`

**Step 1: Write failing classifier tests**

Use a namespace import so a missing export produces an assertion failure rather
than a module-load error. Assert that `getActionPlanRoundNotice` exists and
returns:

```javascript
'incomplete'       // stream_completed === false
'usage_unavailable' // stream_completed === true and usage_recorded === false
'usage_unavailable' // legacy content + duration + zero-only usage
null               // completed stream with positive usage
```

Assert an abnormal saved `finish_reason: 'length'` is incomplete.

**Step 2: Run classifier tests and verify RED**

Run:

```powershell
npm --prefix src/webapp test -- src/webapp/src/utils/actionPlanStats.test.js
```

Expected: FAIL because the classifier does not exist and the legacy helper
still equates zero usage with incomplete output.

**Step 3: Implement the classifier**

Add normalized normal-finish-reason handling and return incomplete only from
explicit incomplete evidence. Treat zero-only or missing usage as unavailable,
including historical `usage_recorded: true` records whose actual token fields
are all zero. Keep `getActionPlanRoundStats` returning null token/rate fields
for unavailable usage.

**Step 4: Run classifier tests and verify GREEN**

Run the Step 2 command again.

Expected: PASS.

**Step 5: Write failing component/copy tests**

Update the source contract test to require `getActionPlanRoundNotice`, the
existing incomplete translation, the new
`action_plan.render.usage_unavailable` translation, and separate
`action-plan-warning` / `action-plan-info` classes.

**Step 6: Run the component test and verify RED**

Run:

```powershell
npm --prefix src/webapp test -- src/webapp/src/components/ActionPlan.test.js
```

Expected: FAIL because the component still has one boolean warning path.

**Step 7: Render precise localized notices**

Replace the two incomplete booleans with notice values. Render the incomplete
copy in the warning style and usage-unavailable copy in a neutral information
style for each round. Change the incomplete Chinese and English copy so it
mentions only abnormal termination. Add neutral copy stating that the reply
ended normally but token and speed statistics are unavailable.

**Step 8: Verify Task 3**

Run:

```powershell
npm --prefix src/webapp test -- src/webapp/src/utils/actionPlanStats.test.js src/webapp/src/components/ActionPlan.test.js
```

Expected: all focused frontend tests pass.

**Step 9: Commit**

```powershell
git add src/webapp/src/utils/actionPlanStats.js src/webapp/src/utils/actionPlanStats.test.js src/webapp/src/components/ActionPlan.jsx src/webapp/src/components/ActionPlan.test.js src/webapp/src/utils/displayCopy.js src/webapp/src/App.css
git commit -m "fix: separate Action Plan stream notices" -m "Render missing usage as a neutral statistics notice, reserve regeneration warnings for explicit incomplete terminal evidence, and classify legacy zero-only records without claiming they were truncated."
```

### Task 4: Complete verification

**Files:**
- No additional tracked changes expected.

**Step 1: Run focused Python regressions**

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest tests/test_llm_client.py tests/test_run_prompt.py -q
```

Expected: all pass.

**Step 2: Run complete frontend tests**

```powershell
npm --prefix src/webapp test -- --run
```

Expected: all pass.

**Step 3: Run frontend lint and production build**

```powershell
npm --prefix src/webapp run lint
npm --prefix src/webapp run build
```

Expected: both exit zero with no new warnings or errors.

**Step 4: Run the full Python suite**

```powershell
.\.venv-backend-runtime-gpu\Scripts\python.exe -m pytest -q
```

Expected: all pass.

**Step 5: Validate the diff and public-repository boundary**

```powershell
git diff --check
git status --short
git diff HEAD~3..HEAD --stat
rg -n "10\.32|AppData|api[_-]?key" docs/plans/2026-08-16-action-plan-stream-usage*.md
```

Expected: no whitespace problems or private runtime details; only the planned
source, tests, CSS, copy, and public design/plan files changed.
