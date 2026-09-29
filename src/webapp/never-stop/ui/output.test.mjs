import test from "node:test";
import assert from "node:assert/strict";
import { appendOutput, emptyOutput } from "./output.mjs";
import { canToggleWithSpace } from "./state.mjs";
const entry = (seq, text = "output") => ({
  seq,
  at: "2026-09-12T12:00:00Z",
  kind: "assistant",
  text,
});
test("cursor advances and overlapping batches do not duplicate output", () => {
  let state = appendOutput(emptyOutput(), {
    entries: [entry(1), entry(2)],
    cursor: 2,
    dropped: false,
  });
  state = appendOutput(state, {
    entries: [entry(2), entry(3)],
    cursor: 3,
    dropped: false,
  });
  assert.deepEqual(
    state.entries.map((item) => item.seq),
    [1, 2, 3],
  );
  assert.equal(state.cursor, 3);
  assert.equal(
    appendOutput(state, { entries: [entry(1)], cursor: 1 }).cursor,
    3,
  );
});
test("bounded buffer retains newest entries and marks omissions", () => {
  const result = appendOutput(emptyOutput(), {
    entries: Array.from({ length: 400 }, (_, i) => entry(i + 1)),
    cursor: 400,
  });
  assert.equal(result.entries.length, 300);
  assert.equal(result.entries[0].seq, 101);
  assert.equal(result.omitted, true);
});
test("multibyte and oversized output stays within byte budget", () => {
  const result = appendOutput(emptyOutput(), {
    entries: [entry(1, "前".repeat(200000))],
    cursor: 1,
  });
  assert.equal(result.entries.length, 1);
  assert.equal(result.entries[0].truncated, true);
  assert.ok(
    new TextEncoder().encode(JSON.stringify(result.entries)).length <=
      256 * 1024,
  );
});
test("server omissions remain visible and fresh project state contains no old entries", () => {
  const state = appendOutput(emptyOutput(), {
    entries: [entry(8)],
    cursor: 8,
    dropped: 7,
  });
  assert.equal(state.omitted, true);
  assert.deepEqual(emptyOutput(), { entries: [], cursor: 0, omitted: false });
});
test("space inside live output is never a project playback shortcut", () => {
  const event = {
    code: "Space",
    target: {
      tagName: "PRE",
      closest: (selector) =>
        selector.includes("[data-live-output]") ? {} : null,
    },
  };
  assert.equal(canToggleWithSpace(event, false), false);
});

test("space while text is selected does not toggle project playback", () => {
  const event = {
    code: "Space",
    target: { tagName: "MAIN" },
    view: { getSelection: () => ({ toString: () => "selected output" }) },
  };
  assert.equal(canToggleWithSpace(event, false), false);
});
