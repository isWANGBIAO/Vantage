import test from "node:test";
import assert from "node:assert/strict";
import {
  canToggleWithSpace,
  reconcileDraft,
  publicationStatus,
} from "./state.mjs";
test("space toggles only outside editing, dialogs and repeated key events", () => {
  const base = {
    code: "Space",
    target: { tagName: "MAIN", closest: () => null },
  };
  assert.equal(canToggleWithSpace(base, false), true);
  for (const override of [
    { repeat: true },
    { ctrlKey: true },
    { isComposing: true },
    { target: { tagName: "INPUT" } },
    { target: { tagName: "TEXTAREA" } },
    { target: { tagName: "BUTTON" } },
    { target: { isContentEditable: true } },
  ])
    assert.equal(canToggleWithSpace({ ...base, ...override }, false), false);
  assert.equal(canToggleWithSpace(base, true), false);
});
test("external changes cannot overwrite locally unsaved edits", () => {
  assert.deepEqual(
    reconcileDraft(
      { text: "mine", base: "old", version: "1" },
      { text: "theirs", version: "2" },
    ),
    {
      conflict: true,
      text: "mine",
      external: { text: "theirs", version: "2" },
    },
  );
  assert.deepEqual(
    reconcileDraft(
      { text: "old", base: "old", version: "1" },
      { text: "new", version: "2" },
    ),
    { conflict: false, text: "new", version: "2" },
  );
  assert.equal(
    reconcileDraft(
      { text: "mine", base: "old", version: "1" },
      { text: "old", version: "1" },
    ),
    null,
  );
});
test("published goal only reports adoption after matching execution revision", () => {
  assert.equal(
    publicationStatus("draft", { publishedGoal: "published" }),
    "草稿未发布",
  );
  assert.equal(
    publicationStatus("goal", {
      publishedGoal: "goal",
      publishedRevision: 2,
      adoptedRevision: 1,
    }),
    "已发布，等待采用",
  );
  assert.equal(
    publicationStatus("goal", {
      publishedGoal: "goal",
      publishedRevision: 2,
      adoptedRevision: 2,
    }),
    "当前执行已采用",
  );
});
