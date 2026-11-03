# Adaptive Action Plan prefix layout

Action Plan builds a complete current snapshot, then arranges its records for
prefix reuse. It does not edit workbooks, omit required inputs, summarize away
records, or send old values followed by corrective patches. Finance-only prompt
consumers keep their explicit existing format until separately migrated.

## Units and stable order

- Markdown documents, Time records and Balance Sheet records are tracked as
  independent units. Dates and source columns remain available; a trailing order
  map restores original source order without putting mutable row ordinals into
  stable record text. Presentation order never substitutes for chronology.
- Existing stable units retain their order. A changed stable unit moves to the
  mutable tail; new units append there, and deleted units disappear. This is
  based on actual fingerprint changes, not a fixed one-day/seven-day window.
- Mutable units can return to stable storage only after at least three distinct
  observations and 24 hours without change. Archive batches are separated by at
  least 24 hours. Already-stable units are never globally resorted; batch
  priority considers size and observed changes without shuffling the prefix.
- Time-dependent summaries, counters, token estimates and runtime clock data
  remain at the tail. Cache diagnostics never appear before stable content.

The private JSON state under the configured history directory stores only
opaque fingerprints, partition order, counts and timestamps. A short
cross-process lock and atomic publication serialize observations. Unsafe paths
are rejected. Bad state is reconstructed; unavailable storage uses a complete
current, deterministic fallback with an explicit diagnostics status.

## Rendering and request boundaries

The versioned compact schema carries columns/source information once; records
do not repeat entire column lists or long internal identifiers. Stable/mutable
records are separately rendered from the current snapshot. Unknown source
metadata is retained in the dynamic tail. The final complete formatted input
still passes the existing token-budget guard; exceeding it is an error, not
permission to silently drop data.

Round two reuses the exact first-round messages and full answer, appending only
the daily-plan requirements. It does not reread or reorder round-one inputs.

## Verification and interpretation

```powershell
python -m pytest -q tests/test_adaptive_prompt_cache.py tests/test_adaptive_prompt_layout.py tests/test_action_plan_adaptive_integration.py tests/test_action_plan_complete_budget.py
```

Synthetic coverage includes old-date edits, inserts/deletes, duplicate records,
newly stable archive batches, repeated edits, cross-day records, concurrent
writers, metadata privacy, storage failure and complete two-round context.

First use changes the prompt format and may require a fresh cache. Measure
provider-returned input hit/miss tokens separately for warm-up and subsequent
calls. The objective is fewer uncached tokens and lower input cost, not adding
redundant text to inflate a percentage. Local common-prefix size is not a
provider cache-hit measurement. Source correctness and complete output take
priority over cache reuse.

DeepSeek caching is best effort, with prefix persistence and eviction controlled
by the provider: https://api-docs.deepseek.com/guides/kv_cache/
