import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Copy,
  ArrowDownToLine,
  Pause,
  Trash2,
  Terminal,
  AlertCircle,
} from "lucide-react";
import { appendOutput, emptyOutput } from "./output.mjs";
const labels = {
  assistant: "助手",
  tool: "工具",
  result: "结果",
  error: "错误",
  status: "状态",
};
const time = (at) =>
  at ? new Date(at).toLocaleTimeString("zh-CN", { hour12: false }) : "";

export default function LiveOutput({ project, invoke, status }) {
  const [expanded, setExpanded] = useState(true);
  const [following, setFollowing] = useState(true);
  const [output, setOutput] = useState(emptyOutput);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clearing, setClearing] = useState(false);
  const outputRef = useRef(output);
  const flight = useRef(false);
  const clearingRef = useRef(false);
  const epoch = useRef(0);
  const viewport = useRef(null);

  useEffect(() => {
    if (!expanded) return;
    let active = true;
    let timer;
    const poll = async () => {
      if (!active) return;
      if (!flight.current && !clearingRef.current) {
        flight.current = true;
        const generation = epoch.current;
        try {
          const batch = await invoke("output.read", {
            id: project.id,
            after: outputRef.current.cursor,
          });
          if (active && generation === epoch.current) {
            if (
              batch.entries?.length ||
              batch.cursor !== outputRef.current.cursor ||
              batch.dropped
            ) {
              const next = appendOutput(outputRef.current, batch);
              outputRef.current = next;
              setOutput(next);
            }
            setError("");
          }
        } catch (failure) {
          if (active && generation === epoch.current)
            setError(failure.message || String(failure));
        } finally {
          flight.current = false;
        }
      }
      if (active) timer = setTimeout(poll, 500);
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [expanded, project.id, invoke]);

  useEffect(() => {
    if (following && expanded && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [following, expanded, output]);

  const clear = async () => {
    clearingRef.current = true;
    setClearing(true);
    epoch.current += 1;
    try {
      await invoke("output.clear", { id: project.id });
      outputRef.current = emptyOutput();
      setOutput(outputRef.current);
      setNotice("显示已清空");
      setError("");
    } catch (failure) {
      setError(failure.message || String(failure));
    } finally {
      clearingRef.current = false;
      setClearing(false);
    }
  };
  const copy = async () => {
    try {
      const text = output.entries
        .map(
          (entry) =>
            `[${entry.at || ""}] ${labels[entry.kind] || entry.kind}\n${entry.text}${entry.truncated ? "\n[单条输出已截断]" : ""}`,
        )
        .join("\n\n");
      await navigator.clipboard.writeText(text);
      setNotice("已复制当前显示的输出");
    } catch (failure) {
      setError(failure.message || String(failure));
    }
  };
  return (
    <section
      className="live-panel"
      data-live-output="true"
      aria-label="实时运行"
    >
      <div className="live-header">
        <button
          className="live-title"
          aria-expanded={expanded}
          aria-controls={`live-${project.id}`}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <Terminal size={17} />
          <strong>实时运行</strong>
        </button>
        <span className="live-agent">
          {project.backend === "claude" ? "Claude Code" : "Codex"}
        </span>
        <span
          className={`live-state ${project.desiredRunning ? "active" : ""}`}
        >
          <i />
          {status}
        </span>
        {expanded && (
          <div className="live-actions">
            <button
              aria-pressed={following}
              onClick={() => setFollowing((value) => !value)}
              title={following ? "暂停自动跟随" : "跟随最新输出"}
            >
              {following ? <Pause size={13} /> : <ArrowDownToLine size={13} />}
              <span>{following ? "暂停跟随" : "跟随最新"}</span>
            </button>
            <button
              onClick={copy}
              disabled={!output.entries.length}
              aria-label="复制实时输出"
              title="复制当前显示"
            >
              <Copy size={14} />
            </button>
            <button
              onClick={clear}
              disabled={clearing}
              aria-label="清空实时输出"
              title="清空显示"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>
      {expanded && (
        <>
          <div className="live-caption">
            <span>实时进程输出 · 只读活动流</span>
            <span aria-live="polite">
              {notice || (following ? "自动跟随" : "已暂停跟随，输出仍在接收")}
            </span>
          </div>
          {error && (
            <div className="live-error" role="status">
              <AlertCircle size={14} />
              {error}
            </div>
          )}
          <div
            id={`live-${project.id}`}
            className="live-viewport"
            ref={viewport}
            role="log"
            data-testid="live-output"
            onKeyDown={(event) => {
              if (event.code === "Space" || event.key === " ")
                event.stopPropagation();
            }}
            aria-label="当前项目实时进程输出"
            aria-live="off"
            tabIndex={0}
          >
            {output.omitted && (
              <p className="live-omitted">
                部分较早输出已省略，当前保留最近的活动。
              </p>
            )}
            {!output.entries.length && (
              <div className="live-empty">
                <Terminal size={25} />
                <p>等待本次运行输出</p>
                <small>
                  {project.desiredRunning
                    ? "Agent 的消息、工具活动和结果将显示在这里。"
                    : "开始或继续项目后，在这里查看实时活动。"}
                </small>
              </div>
            )}
            {output.entries.map((entry) => (
              <article
                className={`live-entry live-kind-${Object.hasOwn(labels, entry.kind) ? entry.kind : "status"}`}
                key={entry.seq}
              >
                <div className="live-entry-meta">
                  <time dateTime={entry.at}>{time(entry.at)}</time>
                  <span>{labels[entry.kind] || "活动"}</span>
                </div>
                <pre>{entry.text}</pre>
                {entry.truncated && (
                  <small className="live-omitted">
                    单条输出过长，显示已截断。
                  </small>
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
