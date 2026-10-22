import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
test("saved file versions, not legacy publication, determine adoption status", () => {
  assert.equal(
    publicationStatus({ text: "unsaved", base: "old", version: "v1" }, {}),
    "未保存",
  );
  assert.equal(
    publicationStatus({ text: "goal", base: "goal", version: "v2" }, { adoptedGoalVersion: "v1" }),
    "已保存，下次执行采用",
  );
  assert.equal(
    publicationStatus({ text: "goal", base: "goal", version: "v2" }, { adoptedGoalVersion: "v2" }),
    "当前执行已采用",
  );
  assert.equal(publicationStatus({ text: " ", base: " ", version: "v3" }, {}), "目标为空，无法运行");
});
test("goal editor saves without a publication gate and explains the next-invocation contract", () => {
  const source = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /发布目标|请先编辑并发布|!project\.publishedGoal/);
  assert.match(source, /保存后用于下一次执行/);
  assert.match(source, /当前轮不会被自动保存中断/);
});
