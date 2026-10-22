# Never Stop live goal contract

Issue #114 product decision: saving `goal.md` makes it the execution target;
there is no separate draft/published gate. The approved contract is:

- `goal.md` is the sole execution source. Read it at start and before every
  actual invocation, including reset and restart. Never fall back to stale
  `publishedGoal` text in a prompt.
- Saving in Vantage is atomic and retains optimistic conflict detection.
  It does not kill a current invocation. The next invocation receives the
  latest saved file, including external edits. UI says this explicitly.
- Missing, blank, invalid UTF-8, unreadable, or oversized goals cannot launch
  a CLI. A running project encountering one pauses with an actionable error.
- Keep legacy publication fields/API for compatibility, but do not use them
  to authorize starting or as a goal fallback. The legacy explicit publish
  action may still interrupt by request; automatic saves never do.
- Expose the hash of the goal actually sent to the current/last invocation.
  The UI compares this with the saved file version rather than claiming a
  snapshot is effective merely because it was published.

Alternatives rejected: retaining save/publish isolation contradicts the user
decision; killing the CLI on every debounced save creates frequent restarts.

Validation uses a local inert CLI recorder, never a real model: save without
publish, external edit, held invocation, next invocation, reset/restart,
invalid files, persistence, editor status and existing process ownership tests.
