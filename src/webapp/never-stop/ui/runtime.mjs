const nonnegative = (value) =>
  Number.isFinite(value) ? Math.max(0, value) : 0;
export function createRuntimeClock(snapshot, wallNow, monotonicNow) {
  const anchor = Number.isFinite(snapshot.runTimerStartedAt)
    ? snapshot.runTimerStartedAt
    : null;
  return {
    total: nonnegative(snapshot.totalRunMs),
    anchor,
    elapsedAtSample: anchor === null ? 0 : nonnegative(wallNow - anchor),
    sampledAt: monotonicNow,
  };
}
export function elapsedRuntime(clock, monotonicNow) {
  return (
    clock.total +
    (clock.anchor === null
      ? 0
      : clock.elapsedAtSample + nonnegative(monotonicNow - clock.sampledAt))
  );
}
export function updateRuntimeClock(previous, snapshot, wallNow, monotonicNow) {
  const next = createRuntimeClock(snapshot, wallNow, monotonicNow);
  if (next.anchor !== null && next.anchor === previous.anchor) {
    next.elapsedAtSample =
      previous.elapsedAtSample + nonnegative(monotonicNow - previous.sampledAt);
  } else if (next.anchor !== null && previous.anchor !== null) {
    // Running snapshots carry a fresh cumulative total and sampling timestamp.
    // Trust that total instead of reapplying a possibly adjusted wall clock.
    next.elapsedAtSample = 0;
  }
  return next;
}
export function formatRuntime(milliseconds) {
  const seconds = Math.floor(nonnegative(milliseconds) / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds / 3600) % 24;
  const minutes = Math.floor(seconds / 60) % 60;
  const value = [hours, minutes, seconds % 60]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return days ? `${days} 天 ${value}` : value;
}
