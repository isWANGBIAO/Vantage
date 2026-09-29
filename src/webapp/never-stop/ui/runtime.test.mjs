import test from "node:test";
import assert from "node:assert/strict";
import {
  createRuntimeClock,
  updateRuntimeClock,
  elapsedRuntime,
  formatRuntime,
} from "./runtime.mjs";
test("active runtime adds existing total and elapsed time using a monotonic clock", () => {
  const clock = createRuntimeClock(
    { totalRunMs: 60000, runTimerStartedAt: 9000 },
    10000,
    500,
  );
  assert.equal(elapsedRuntime(clock, 2500), 63000);
});
test("refreshing the same anchor cannot jump with adjusted wall time", () => {
  const snapshot = { totalRunMs: 60000, runTimerStartedAt: 9000 };
  const clock = createRuntimeClock(snapshot, 10000, 500);
  const forward = updateRuntimeClock(clock, snapshot, 3600010000, 2500);
  assert.equal(elapsedRuntime(forward, 3500), 64000);
  const backward = updateRuntimeClock(forward, snapshot, 0, 4500);
  assert.equal(elapsedRuntime(backward, 5500), 66000);
});
test("paused runtime is frozen and resumed runtime starts from the new anchor", () => {
  const active = createRuntimeClock(
    { totalRunMs: 5000, runTimerStartedAt: 1000 },
    2000,
    100,
  );
  const paused = updateRuntimeClock(
    active,
    { totalRunMs: 7000, runTimerStartedAt: null },
    3000,
    1100,
  );
  assert.equal(elapsedRuntime(paused, 100000), 7000);
  const resumed = updateRuntimeClock(
    paused,
    { totalRunMs: 7000, runTimerStartedAt: 9000 },
    9500,
    200000,
  );
  assert.equal(elapsedRuntime(resumed, 201000), 8500);
});
test("missing legacy data and future anchors never create negative or invented time", () => {
  assert.equal(elapsedRuntime(createRuntimeClock({}, 1000, 0), 90000), 0);
  assert.equal(
    elapsedRuntime(
      createRuntimeClock({ totalRunMs: 0, runTimerStartedAt: 2000 }, 1000, 100),
      100,
    ),
    0,
  );
});
test("format runtime as HH:MM:SS with days beyond 24 hours", () => {
  assert.equal(formatRuntime(0), "00:00:00");
  assert.equal(formatRuntime(3661999), "01:01:01");
  assert.equal(formatRuntime(86400000), "1 天 00:00:00");
  assert.equal(formatRuntime(176461000), "2 天 01:01:01");
});

test("fresh cumulative snapshots do not reapply a wall-clock jump", () => {
  const clock = createRuntimeClock(
    { totalRunMs: 60000, runTimerStartedAt: 10000 },
    10000,
    100,
  );
  const next = updateRuntimeClock(
    clock,
    { totalRunMs: 62000, runTimerStartedAt: 12000 },
    3600012000,
    2100,
  );
  assert.equal(elapsedRuntime(next, 3100), 63000);
});
