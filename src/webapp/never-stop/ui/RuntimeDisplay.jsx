import { useEffect, useRef, useState } from "react";
import { Timer } from "lucide-react";
import {
  createRuntimeClock,
  updateRuntimeClock,
  elapsedRuntime,
  formatRuntime,
} from "./runtime.mjs";

export default function RuntimeDisplay({ totalRunMs, runTimerStartedAt }) {
  const clock = useRef(null);
  if (!clock.current)
    clock.current = createRuntimeClock(
      { totalRunMs, runTimerStartedAt },
      Date.now(),
      performance.now(),
    );
  const [milliseconds, setMilliseconds] = useState(() =>
    elapsedRuntime(clock.current, performance.now()),
  );
  useEffect(() => {
    const now = performance.now();
    clock.current = updateRuntimeClock(
      clock.current,
      { totalRunMs, runTimerStartedAt },
      Date.now(),
      now,
    );
    setMilliseconds(elapsedRuntime(clock.current, now));
    if (clock.current.anchor === null) return;
    const timer = setInterval(
      () => setMilliseconds(elapsedRuntime(clock.current, performance.now())),
      1000,
    );
    return () => clearInterval(timer);
  }, [totalRunMs, runTimerStartedAt]);
  return (
    <div
      className="project-runtime"
      title="累计运行与自动重试时间；暂停和离线不计。旧项目从本次升级后开始累计。"
    >
      <span>
        <Timer size={13} />
        累计运行
      </span>
      <output data-testid="project-runtime" aria-label="累计运行时间">
        {formatRuntime(milliseconds)}
      </output>
    </div>
  );
}
