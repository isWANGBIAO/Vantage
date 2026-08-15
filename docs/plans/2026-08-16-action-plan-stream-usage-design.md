# Action Plan Stream Usage and Completion Design

## Status

Approved on 2026-08-16. The user requested the complete implementation after
the current Action Plan incorrectly described a normally completed local-model
response as potentially incomplete when streaming usage was absent.

## Evidence and root cause

The configured OpenAI-compatible local route was probed with a minimal,
non-private prompt. A non-streaming request returned token usage. The existing
streaming request returned a normal `stop` finish reason and `[DONE]`, but no
usage event. The same streaming request with
`stream_options.include_usage=true` returned usage as a final SSE event.

Vantage currently sends `stream=true` without requesting streamed usage. The
LLM client correctly rejects streams without `[DONE]` or a normal finish reason,
but it does not persist that successful terminal evidence in the Action Plan
statistics. Separately, the Action Plan retry accumulator initializes missing
usage as explicit zero totals. The frontend then treats content plus duration
plus zero totals as evidence that the stream may be incomplete. This conflates
three distinct states: recorded usage, unavailable usage, and an incomplete
stream.

## Goals

- Request token usage for OpenAI-compatible streaming completions.
- Preserve compatibility with providers that reject `stream_options`.
- Persist successful stream-completion evidence independently of usage.
- Preserve missing usage as unavailable rather than converting it to zero.
- Show a neutral informational notice for unavailable usage.
- Show the regenerate warning only for explicit incomplete-stream evidence.
- Keep existing retry and failure behavior for missing or abnormal terminal
  events.

## Transport and compatibility

Every streaming chat payload requests:

```json
{"stream_options":{"include_usage":true}}
```

If an OpenAI-compatible provider responds with a client error that explicitly
identifies `stream_options` as unsupported, Vantage retries that same provider
and model once without the field. It does not silently switch models merely
because usage reporting is unsupported. A successfully completed fallback
stream remains valid, but its usage is marked unavailable.

The streaming parser retains the last dictionary-shaped usage event and ignores
intermediate `null` usage values. After terminal validation succeeds, the
result records:

- `stream_completed: true`;
- `stream_terminal_event: done` when `[DONE]` was observed, otherwise
  `finish_reason`;
- the normalized successful finish reason when one was supplied.

Abnormal finish reasons and streams without any trustworthy terminal event
continue to raise `StreamIncompleteError`, remain failed in model-call history,
and follow the existing Action Plan retry contract.

## Statistics and saved payloads

The retry accumulator tracks whether any attempt actually supplied usage.
Missing usage remains an empty mapping and becomes
`usage_recorded: false` with null token fields. Recorded usage is summed across
accepted attempts as before. Top-level `reasoning_tokens`, used by the current
local route, is normalized into the existing completion-reasoning statistic.

Per-round Action Plan statistics persist the three stream fields alongside
duration, usage, model, and route metadata. No prompt or response content is
added to statistics.

## Frontend behavior

The frontend classifies each saved round into one of three states:

1. `incomplete`: explicit `stream_completed: false` or an abnormal saved finish
   reason. Render the existing prominent warning and instruct regeneration.
2. `usage_unavailable`: content completed but token usage was not recorded.
   Render a neutral information notice explaining that the reply ended normally
   but token and speed statistics are unavailable.
3. no notice: usage exists and there is no incomplete evidence.

Legacy records with content, duration, and zero-only token fields have no
trustworthy incomplete evidence. They are treated as usage unavailable instead
of incomplete. This prevents the current false warning while avoiding a false
claim that historical token counts were measured.

## Tests and verification

Regression coverage will prove that:

- streaming payloads request usage and retain a final usage event;
- a provider that explicitly rejects `stream_options` is retried once without
  it;
- normal terminal metadata is returned and saved;
- incomplete and length-limited streams remain failures;
- missing usage survives retry aggregation as unavailable rather than zeros;
- local-style top-level reasoning tokens are normalized;
- frontend classification distinguishes incomplete, usage-unavailable, and
  complete-with-usage states, including legacy zero-only records;
- Action Plan renders separate localized messages and neutral/warning styles.

Focused Python and frontend tests run first, followed by the complete relevant
test suites, frontend lint/build, and whitespace validation. No private prompt,
response, endpoint, credential, or local log is committed.
