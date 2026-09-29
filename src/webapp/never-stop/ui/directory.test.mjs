import test from "node:test";
import assert from "node:assert/strict";
import { projectScopeKey } from "./state.mjs";
test("changing root isolates delayed progress responses for the same project", () => {
  const previous = { id: "same-project", root: "C:/old" };
  const current = { id: "same-project", root: "D:/new" };
  const cache = {};
  cache[projectScopeKey(current)] = { markdown: "new progress" };
  // A pending read from the old root returns after the project has moved.
  cache[projectScopeKey(previous)] = { markdown: "old progress" };
  assert.equal(cache[projectScopeKey(current)].markdown, "new progress");
});
test("project and directory identity cannot collide through delimiter characters", () => {
  assert.notEqual(
    projectScopeKey({ id: "a:b", root: "c" }),
    projectScopeKey({ id: "a", root: "b:c" }),
  );
  assert.equal(projectScopeKey(null), null);
});
