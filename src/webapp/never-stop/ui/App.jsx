import RuntimeDisplay from "./RuntimeDisplay.jsx";
import LiveOutput from "./LiveOutput.jsx";
import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReactECharts from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { RadarChart } from "echarts/charts";
import { RadarComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([RadarChart, RadarComponent, CanvasRenderer]);
import {
  Infinity as InfinityIcon,
  Plus,
  Play,
  Pause,
  Folder,
  Settings,
  Server,
  X,
  ArrowUpRight,
  FileText,
  Sparkles,
  Shield,
  RotateCcw,
  AlertCircle,
  Copy,
  Save,
  ChevronRight,
  Trash2,
  RefreshCw,
} from "lucide-react";
import {
  canToggleWithSpace,
  projectScopeKey,
  reconcileDraft,
  publicationStatus,
} from "./state.mjs";
const invoke = (method, payload = {}) =>
  window.neverStop
    ? window.neverStop.invoke(method, payload)
    : Promise.reject(
        new Error("桌面连接不可用。请使用 Never Stop 独立桌面入口启动。"),
      );
const message = (e) => e?.message || String(e);
const Markdown = ({ text }) => (
  <div className="markdown">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ children }) => <span>{children}</span>,
        img: ({ alt }) => <span>[图片：{alt}]</span>,
      }}
    >
      {text || "暂无内容。"}
    </ReactMarkdown>
  </div>
);
const date = (value) =>
  value ? new Date(value).toLocaleString("zh-CN") : "尚未更新";
const status = (p) =>
  ({
    running: "正在运行",
    paused: "已暂停",
    retrying: "正在自动重试",
    starting: "正在启动",
    switching: "正在切换",
    stopping: "正在停止",
  })[p.status] || (p.desiredRunning ? "准备运行" : "已暂停");
export default function App() {
  const [state, setState] = useState({
    projects: [],
    resources: [],
    settings: {},
    principles: "",
  });
  const [selected, setSelected] = useState(null),
    [panel, setPanel] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState({}),
    [modal, setModal] = useState(null),
    [draftDirty, setDraftDirty] = useState({});
  const project = state.projects.find((p) => p.id === selected);
  const progressKey = projectScopeKey(project);
  const reportDraftState = useCallback((id, dirty) => {
    setDraftDirty((previous) =>
      previous[id] === dirty ? previous : { ...previous, [id]: dirty },
    );
  }, []);
  const refresh = useCallback(async () => {
    try {
      const next = await invoke("state");
      setState(next);
      setSelected((id) =>
        next.projects.some((p) => p.id === id)
          ? id
          : next.projects[0]?.id || null,
      );
    } catch (e) {
      setError(message(e));
    }
  }, []);
  useEffect(() => {
    refresh();
    const unsub = window.neverStop?.onChange((event) => {
      if (event?.selectedProjectId) {
        setSelected(event.selectedProjectId);
        setPanel(null);
      }
      refresh();
    });
    const timer = setInterval(refresh, 2500);
    return () => {
      unsub?.();
      clearInterval(timer);
    };
  }, [refresh]);
  const readProgress = useCallback(async () => {
    if (!selected || !progressKey) return;
    try {
      const result = await invoke("progress.read", { id: selected });
      setProgress((prev) => ({ ...prev, [progressKey]: result }));
    } catch (e) {
      setProgress((prev) => ({
        ...prev,
        [progressKey]: { ...prev[progressKey], error: message(e) },
      }));
    }
  }, [selected, progressKey]);
  useEffect(() => {
    readProgress();
    const timer = setInterval(readProgress, 1800);
    return () => clearInterval(timer);
  }, [readProgress]);
  const run = useCallback(
    async (method, payload = {}) => {
      setBusy(true);
      try {
        const result = await invoke(method, payload);
        await refresh();
        return result;
      } catch (e) {
        setError(message(e));
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );
  const toggle = useCallback(() => {
    if (!project || busy) return;
    if (!project.desiredRunning && !project.publishedGoal?.trim()) {
      setPanel("目标");
      setError("请先编辑并发布目标，再开始运行。");
      return;
    }
    run(project.desiredRunning ? "project.pause" : "project.start", {
      id: project.id,
    }).catch(() => {});
  }, [project, busy, run]);
  useEffect(() => {
    const handler = (e) => {
      if (canToggleWithSpace(e, !!panel || !!modal)) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggle, panel, modal]);
  const current = progress[progressKey] || {},
    snapshot = current.snapshot,
    axes = snapshot?.radar?.axes || [];
  const openPanel = (name) => setPanel(name);
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text || "");
    } catch (e) {
      setError(message(e));
    }
  };
  return (
    <div className="app">
      <aside className="sidebar" inert={panel || modal ? true : undefined}>
        <div className="brand">
          <span className="brand-icon">
            <InfinityIcon size={26} />
          </span>
          <div>
            Never Stop<small>持续向前，由你掌舵</small>
          </div>
        </div>
        <div className="sidebar-heading">
          工作空间{" "}
          <button
            className="icon"
            aria-label="添加项目"
            onClick={() => setModal("add")}
          >
            <Plus size={17} />
          </button>
        </div>
        <nav className="projects">
          {state.projects.map((p) => (
            <button
              className={`project-item ${p.id === selected ? "active" : ""}`}
              key={p.id}
              onClick={() => {
                setSelected(p.id);
                setPanel(null);
              }}
            >
              <Folder size={18} />
              <span>
                {p.name || p.root.split(/[\\/]/).pop()}
                <small>
                  {p.backend === "claude" ? "Claude Code" : "Codex"}
                </small>
              </span>
              <i className={p.desiredRunning ? "live" : ""} />
            </button>
          ))}
          {!state.projects.length && (
            <p className="sidebar-empty">
              添加一个项目，
              <br />
              从你的目标开始。
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <button onClick={() => openPanel("我的资源")}>
            <Server size={18} />
            我的资源<span>{state.resources.length}</span>
          </button>
          <button onClick={() => openPanel("设置")}>
            <Settings size={18} />
            设置
          </button>
          <p>
            <i className="live" />
            关闭窗口后，运行项目继续工作
          </p>
        </div>
      </aside>
      <main inert={panel || modal ? true : undefined}>
        <header>
          <div className="breadcrumb">
            工作空间
            <ChevronRight size={15} />
            {project?.name || "欢迎"}
          </div>
          <span className="edition">
            独立 Demo · {state.appVersion ? `v${state.appVersion}` : "开发版"}
          </span>
        </header>
        {error && (
          <div role="alert" className="banner">
            <AlertCircle size={17} />
            <span>{error}</span>
            <button
              className="icon"
              aria-label="关闭提示"
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {project ? (
          <>
            <section className="project-heading">
              <div>
                <p className="eyebrow">让目标持续生长</p>
                <h1>{project.name}</h1>
                <div className="project-directory">
                  <p className="root-path" title={project.root}>
                    {project.root}
                  </p>
                  <button
                    className="directory-change"
                    aria-label="更改目录"
                    disabled={busy || !!draftDirty[project.id]}
                    title={
                      draftDirty[project.id]
                        ? "请先保存目标草稿并解决编辑冲突"
                        : "更改项目目录"
                    }
                    onClick={() => setModal("directory")}
                  >
                    更改目录
                  </button>
                </div>
                {draftDirty[project.id] && (
                  <small className="directory-draft-hint">
                    目标草稿尚未保存或存在冲突，保存后可更改目录。
                  </small>
                )}
              </div>
              <div className="project-labels">
                <span className="pill">
                  {project.backend === "claude" ? "Claude Code" : "Codex"}
                </span>
                <span
                  className={`pill ${project.desiredRunning ? "green" : ""}`}
                >
                  <i className={project.desiredRunning ? "live" : ""} />
                  {status(project)}
                </span>
              </div>
            </section>
            <section className="overview">
              <div className="overview-top">
                <span>目标进展</span>
                <span className="self-rated">Agent 自评</span>
              </div>
              <div className="visual">
                <div className="radar">
                  {axes.length >= 3 ? (
                    <ReactECharts
                      echarts={echarts}
                      style={{ height: 330, width: "100%" }}
                      option={{
                        animationDuration: 300,
                        radar: {
                          indicator: axes.map((a) => ({
                            name: a.label,
                            max: 100,
                          })),
                          radius: "64%",
                          axisName: { color: "#727e77", fontSize: 12 },
                          splitNumber: 4,
                          splitArea: {
                            areaStyle: { color: ["#fafbf8", "#f3f6f1"] },
                          },
                          splitLine: { lineStyle: { color: "#dfe6dd" } },
                          axisLine: { lineStyle: { color: "#dfe6dd" } },
                        },
                        series: [
                          {
                            type: "radar",
                            symbolSize: 5,
                            lineStyle: { color: "#548665", width: 2 },
                            itemStyle: { color: "#548665" },
                            areaStyle: { color: "rgba(84,134,101,.20)" },
                            data: [{ value: axes.map((a) => a.value) }],
                          },
                        ],
                      }}
                    />
                  ) : (
                    <div className="radar-empty">
                      <div className="empty-orbit">
                        <Sparkles size={27} />
                      </div>
                      <strong>
                        {axes.length ? "雷达维度不足" : "等待第一份自评"}
                      </strong>
                      <p>
                        {axes.length
                          ? "至少三个维度后显示雷达图"
                          : "Agent 更新进展后，图表将在这里呈现"}
                      </p>
                    </div>
                  )}
                </div>
                <div className="progress-number">
                  <p>总体进度</p>
                  <div>
                    {snapshot?.overall_percent == null ? (
                      <span className="no-score">—</span>
                    ) : (
                      <>
                        {snapshot.overall_percent}
                        <span>%</span>
                      </>
                    )}
                  </div>
                  <small>
                    {snapshot?.overall_percent == null
                      ? "尚无进度评分"
                      : "达到 100% 后仍持续运行，直到你暂停"}
                  </small>
                  <div className="update">
                    <span className="tiny-dot" />
                    最近更新
                    <br />
                    <b>{date(snapshot?.updated_at)}</b>
                  </div>
                </div>
              </div>
              <div className="overview-bottom">
                <div>
                  <span
                    className={`tiny-dot ${project.desiredRunning ? "on" : ""}`}
                  />
                  {project.desiredRunning
                    ? "工作正在后台持续进行"
                    : "准备好时，继续向目标前进"}
                </div>
                <RuntimeDisplay
                  key={project.id}
                  totalRunMs={project.totalRunMs}
                  runTimerStartedAt={project.runTimerStartedAt}
                />
                <button
                  className={`primary control ${project.desiredRunning ? "pause" : ""}`}
                  disabled={busy}
                  onClick={toggle}
                >
                  {project.desiredRunning ? (
                    <Pause size={18} />
                  ) : (
                    <Play size={18} />
                  )}{" "}
                  {project.desiredRunning ? "暂停" : "开始 / 继续"}
                  <kbd>空格</kbd>
                </button>
              </div>
            </section>
            <LiveOutput
              key={projectScopeKey(project)}
              project={project}
              invoke={invoke}
              status={status(project)}
            />
            {current.error && (
              <div className="data-warning">
                <AlertCircle size={15} />
                进度数据暂不可用：
                {typeof current.error === "string"
                  ? current.error
                  : message(current.error)}
                。保留最近有效展示，运行不会停止。
              </div>
            )}
            <section className="links">
              {[
                ["目标", FileText, "编辑、保存与发布"],
                ["进展", ArrowUpRight, "查看最新工作摘要"],
                ["建议", Sparkles, "留给你的思考"],
                ["执行原则", Shield, "每轮实际发送的原则"],
              ].map(([name, Icon, description]) => (
                <button key={name} onClick={() => openPanel(name)}>
                  {React.createElement(Icon, { size: 21 })}
                  <strong>{name}</strong>
                  <small>{description}</small>
                  <ChevronRight size={15} />
                </button>
              ))}
            </section>
            <footer>
              <button onClick={() => setModal("reset")}>
                <RotateCcw size={14} />
                重置上下文
              </button>
              <button onClick={() => setModal("stop")}>强制结束项目</button>
              <button onClick={() => setModal("remove")}>移除项目</button>
              {project.error && (
                <button
                  className="error-link"
                  onClick={() => openPanel("错误")}
                >
                  <AlertCircle size={14} />
                  执行错误 · {project.error.count || 1} 次
                </button>
              )}
              <span>会话与文件保留 · 由你决定何时结束</span>
            </footer>
          </>
        ) : (
          <section className="welcome">
            <span className="welcome-symbol">
              <InfinityIcon size={68} />
            </span>
            <p className="eyebrow">一个目标，持续前进</p>
            <h1>把下一步，交给持续行动。</h1>
            <p>
              选择项目，写下目标。Never Stop 持续调用你的 Agent，
              <br />
              让你随时看进展、调整方向、暂停工作。
            </p>
            <button className="primary" onClick={() => setModal("add")}>
              <Plus size={18} />
              添加第一个项目
            </button>
            <small>使用你已配置的 Claude Code 或 Codex</small>
          </section>
        )}
      </main>
      {panel && <div className="scrim" onClick={() => setPanel(null)} />}
      {state.projects.map((editorProject) => {
        const visible = panel === "目标" && selected === editorProject.id;
        return (
          <div
            key={projectScopeKey(editorProject)}
            className={`drawer ${visible ? "visible" : ""}`}
            role={visible ? "dialog" : undefined}
            aria-modal={visible ? true : undefined}
            aria-label="目标"
            inert={visible ? undefined : true}
          >
            <DrawerHead title="目标" close={() => setPanel(null)} />
            <GoalEditor
              project={editorProject}
              visible={visible}
              onDraftState={reportDraftState}
              run={run}
              onError={setError}
            />
          </div>
        );
      })}
      {panel && panel !== "目标" && (
        <section
          className="drawer visible"
          role="dialog"
          aria-modal="true"
          aria-label={panel}
        >
          <DrawerHead title={panel} close={() => setPanel(null)} />
          <div className="drawer-body">
            {panel === "进展" && (
              <ProgressView markdown={current.markdown} copy={copy} />
            )}{" "}
            {panel === "建议" && (
              <>
                <p className="hint">
                  建议由 Agent 提出。需要调整目标时，请自行编辑并发布。
                </p>
                <Markdown text={snapshot?.suggestions_markdown} />
              </>
            )}{" "}
            {panel === "执行原则" && (
              <Markdown
                text={
                  typeof state.principles === "string"
                    ? state.principles
                    : state.principles?.text
                }
              />
            )}{" "}
            {panel === "错误" && (
              <>
                <p className="hint">
                  {date(project?.error?.at)} · 重复 {project?.error?.count || 1}{" "}
                  次
                </p>
                <pre className="error-text">
                  {project?.error?.message || "当前没有执行错误。"}
                </pre>
              </>
            )}{" "}
            {panel === "我的资源" && (
              <Resources
                resources={state.resources}
                project={project}
                run={run}
                onError={setError}
              />
            )}{" "}
            {panel === "设置" && (
              <Preferences settings={state.settings} run={run} />
            )}
          </div>
        </section>
      )}
      {modal && (
        <div className="modal-scrim">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "add"
                ? "添加项目"
                : modal === "directory"
                  ? "更改项目目录"
                  : "项目操作"
            }
          >
            <DrawerHead
              title={
                {
                  add: "添加项目",
                  reset: "重置上下文",
                  remove: "移除项目",
                  stop: "强制结束项目",
                  directory: "更改项目目录",
                }[modal]
              }
              close={() => setModal(null)}
            />
            {modal === "add" ? (
              <AddProject
                run={run}
                done={(id) => {
                  setSelected(id);
                  setModal(null);
                  setPanel("目标");
                }}
              />
            ) : modal === "directory" ? (
              <ChangeDirectory
                key={projectScopeKey(project)}
                project={project}
                run={run}
                hasUnsaved={!!draftDirty[project.id]}
                done={(warnings = []) => {
                  setModal(null);
                  setPanel(null);
                  setError(
                    warnings.length ? `目录已更改：${warnings.join("；")}` : "",
                  );
                }}
              />
            ) : (
              <div className="modal-body">
                <p>
                  {modal === "reset"
                    ? "下一次调用将使用全新会话。目标、代码和进展文件保留；暂停的项目仍保持暂停。"
                    : modal === "remove"
                      ? "停止本应用管理的执行并移除项目记录。项目目录与源文件会保留。"
                      : "立即停止本项目续跑并中断受管理的执行。已保存文件保留；远端脱离会话的任务不在控制范围内。"}
                </p>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    run(
                      modal === "reset"
                        ? "project.reset"
                        : modal === "remove"
                          ? "project.remove"
                          : "project.pause",
                      { id: project.id },
                    )
                      .then(() => setModal(null))
                      .catch(() => {})
                  }
                >
                  确认
                  {modal === "reset"
                    ? "重置"
                    : modal === "remove"
                      ? "移除"
                      : "结束"}
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
function DrawerHead({ title, close }) {
  return (
    <div className="drawer-head">
      <h2>{title}</h2>
      <button className="icon" aria-label={`关闭${title}`} onClick={close}>
        <X size={20} />
      </button>
    </div>
  );
}
function GoalEditor({ project, visible, run, onError, onDraftState }) {
  const [text, setText] = useState(""),
    [ready, setReady] = useState(false),
    [preview, setPreview] = useState(false),
    [conflict, setConflict] = useState(null),
    [saveState, setSaveState] = useState("正在读取"),
    [saving, setSaving] = useState(false);
  const local = useRef({ text: "", base: "", version: null }),
    lock = useRef(false),
    conflictRef = useRef(null),
    mounted = useRef(true);
  useEffect(() => {
    onDraftState(
      project.id,
      saving || !!conflict || local.current.text !== local.current.base,
    );
  }, [project.id, onDraftState, text, saving, conflict, saveState]);
  const apply = useCallback((external) => {
    local.current = {
      text: external.text,
      base: external.text,
      version: external.version,
    };
    setText(external.text);
    setSaveState("草稿已保存");
  }, []);
  useEffect(() => {
    let active = true;
    mounted.current = true;
    const read = async () => {
      try {
        if (!visible || lock.current) return;
        const external = await invoke("goal.read", { id: project.id });
        if (!active || lock.current) return;
        if (local.current.version === null) {
          apply(external);
          setReady(true);
        } else {
          const result = reconcileDraft(local.current, external);
          if (result?.conflict) {
            conflictRef.current = result.external;
            setConflict(result.external);
            setSaveState("发现外部编辑冲突");
          } else if (result) {
            apply(external);
          }
        }
      } catch (e) {
        if (active) onError(message(e));
      }
    };
    read();
    const timer = setInterval(read, 1400);
    return () => {
      active = false;
      mounted.current = false;
      clearInterval(timer);
    };
  }, [project.id, visible, apply, onError]);
  const save = useCallback(async () => {
    if (lock.current || conflictRef.current || local.current.version === null)
      return false;
    if (local.current.text === local.current.base) return true;
    lock.current = true;
    setSaving(true);
    const submitted = { ...local.current };
    try {
      const result = await invoke("goal.save", {
        id: project.id,
        text: submitted.text,
        version: submitted.version,
      });
      local.current.base = result.text;
      local.current.version = result.version;
      if (mounted.current)
        setSaveState(
          local.current.text === result.text ? "草稿已保存" : "待保存",
        );
      return true;
    } catch (e) {
      try {
        const external = await invoke("goal.read", { id: project.id });
        if (external.version !== submitted.version) {
          conflictRef.current = external;
          setConflict(external);
          setSaveState("发现外部编辑冲突");
        } else onError(message(e));
      } catch {
        onError(message(e));
      }
      return false;
    } finally {
      lock.current = false;
      if (mounted.current) setSaving(false);
    }
  }, [project.id, onError]);
  useEffect(() => {
    if (!ready || conflict) return;
    const timer = setTimeout(() => save(), 650);
    return () => clearTimeout(timer);
  }, [text, ready, conflict, save, saving]);
  const publish = async () => {
    const publishedText = local.current.text;
    if (await save()) {
      try {
        await run("goal.publish", { id: project.id, text: publishedText });
      } catch {
        /* run() already reports the error in the application banner. */
      }
    }
  };
  return (
    <>
      <div className="editor-tools">
        <div className="segmented">
          <button
            className={!preview ? "selected" : ""}
            onClick={() => setPreview(false)}
          >
            编辑
          </button>
          <button
            className={preview ? "selected" : ""}
            onClick={() => setPreview(true)}
          >
            预览
          </button>
        </div>
        <span>{saveState}</span>
        <button
          className="icon"
          aria-label="保存草稿 Ctrl+S"
          onClick={save}
          disabled={!ready || saving || !!conflict}
        >
          <Save size={17} />
        </button>
      </div>
      <div
        className="editor-content"
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
            e.preventDefault();
            save();
          }
        }}
      >
        {preview ? (
          <Markdown text={text} />
        ) : (
          <textarea
            aria-label="目标 Markdown"
            spellCheck={false}
            disabled={!ready}
            placeholder={"# 我的目标\n\n描述你希望 Agent 持续推进的工作……"}
            value={text}
            onChange={(e) => {
              local.current.text = e.target.value;
              setText(e.target.value);
              setSaveState("待保存");
            }}
          />
        )}
        {conflict && (
          <div className="conflict" role="alert">
            <h3>goal.md 已在外部修改</h3>
            <p>
              本地草稿已保留。选择采用外部版本，或在编辑器中手动合并后保存本地内容。
            </p>
            <div className="conflict-columns">
              <div>
                <strong>本地草稿</strong>
                <pre>{text}</pre>
              </div>
              <div>
                <strong>外部内容</strong>
                <pre>{conflict.text}</pre>
              </div>
            </div>
            <button
              onClick={() => {
                apply(conflict);
                conflictRef.current = null;
                setConflict(null);
              }}
            >
              采用外部版本
            </button>
            <button
              onClick={() => {
                local.current.base = conflict.text;
                local.current.version = conflict.version;
                conflictRef.current = null;
                setConflict(null);
                setSaveState("待保存");
              }}
            >
              保留本地 / 已手动合并
            </button>
          </div>
        )}
      </div>
      <div className="editor-footer">
        <p>
          <span className="pill">{publicationStatus(text, project)}</span>
          <small>自动保存仅更新草稿。撤销 / 重做使用系统快捷键。</small>
        </p>
        <button
          className="primary"
          disabled={!ready || !text.trim() || !!conflict || saving}
          onClick={publish}
        >
          发布目标
          <ArrowUpRight size={16} />
        </button>
      </div>
    </>
  );
}
function ProgressView({ markdown, copy }) {
  const [raw, setRaw] = useState(false);
  return (
    <>
      <div className="toolbar">
        <div className="segmented">
          <button
            className={!raw ? "selected" : ""}
            onClick={() => setRaw(false)}
          >
            阅读
          </button>
          <button
            className={raw ? "selected" : ""}
            onClick={() => setRaw(true)}
          >
            原文
          </button>
        </div>
        <button onClick={() => copy(markdown)}>
          <Copy size={15} />
          复制原文
        </button>
      </div>
      {raw ? (
        <pre className="raw">{markdown || "尚无进展摘要。"}</pre>
      ) : (
        <Markdown text={markdown} />
      )}
    </>
  );
}
function AddProject({ run, done }) {
  const [root, setRoot] = useState(""),
    [backend, setBackend] = useState("codex"),
    [discovery, setDiscovery] = useState(null),
    [loading, setLoading] = useState(false);
  const pick = async (create) => {
    try {
      const path = await run("project.pick", { create });
      if (path) setRoot(typeof path === "string" ? path : path.root);
    } catch {
      /* run() already reports the error in the application banner. */
    }
  };
  return (
    <div className="modal-body">
      <p className="hint">
        在选中的目录中创建独立会话，使用本机已配置的 Agent。
      </p>
      <label>
        项目目录
        <input
          value={root}
          placeholder="选择已有目录，或新建项目目录"
          onChange={(e) => setRoot(e.target.value)}
        />
      </label>
      <div className="toolbar">
        <button onClick={() => pick(false)}>
          <Folder size={16} />
          选择目录
        </button>
        <button onClick={() => pick(true)}>
          <Plus size={16} />
          新建目录
        </button>
      </div>
      <label>
        Agent
        <select value={backend} onChange={(e) => setBackend(e.target.value)}>
          <option value="codex">Codex</option>
          <option value="claude">Claude Code</option>
        </select>
      </label>
      <button
        className="text-button"
        disabled={loading}
        onClick={async () => {
          setLoading(true);
          try {
            setDiscovery(await run("projects.discover"));
          } catch {
            /* run() reports the error in the application banner. */
          } finally {
            setLoading(false);
          }
        }}
      >
        <RefreshCw size={15} />{" "}
        {loading ? "正在发现…" : "从本机 Agent 记录发现项目"}
      </button>
      {discovery && (
        <div className="discovery">
          {discovery.projects?.map((p) => (
            <button
              key={`${p.root}:${p.source}`}
              onClick={() => setRoot(p.root)}
            >
              <Folder size={15} />
              <span>
                {p.root}
                <small>{p.source}</small>
              </span>
            </button>
          ))}
          {!discovery.projects?.length && (
            <p>没有发现可用项目，仍可手动选择目录。</p>
          )}
          {discovery.warnings?.map((w, i) => (
            <p key={i}>{typeof w === "string" ? w : message(w)}</p>
          ))}
        </div>
      )}
      <button
        className="primary wide"
        disabled={!root.trim() || loading}
        onClick={async () => {
          setLoading(true);
          try {
            const result = await run("project.add", { root, backend });
            done(result.id || result.project?.id);
          } catch {
            /* run() reports the error in the application banner. */
          } finally {
            setLoading(false);
          }
        }}
      >
        添加项目
        <ArrowUpRight size={16} />
      </button>
    </div>
  );
}
function Resources({ resources, project, run, onError }) {
  const [editing, setEditing] = useState(null),
    [form, setForm] = useState({}),
    [saving, setSaving] = useState(false),
    [importWarnings, setImportWarnings] = useState([]);
  const edit = (r) => {
    setEditing(r?.id || "new");
    setForm(
      r
        ? { ...r, password: "" }
        : {
            name: "",
            host: "",
            port: 22,
            username: "",
            keyPath: "",
            notes: "",
            password: "",
          },
    );
  };
  const selected = project?.resourceIds || [];
  return (
    <>
      <p className="hint">
        登记连接信息，再选择提供给当前项目的资源。连接与实验安排由 Agent 决定。
      </p>
      <div className="toolbar">
        <button onClick={() => edit(null)}>
          <Plus size={16} />
          新增资源
        </button>
        <button
          onClick={() =>
            run("resources.import")
              .then((result) => setImportWarnings(result.warnings || []))
              .catch(() => {})
          }
        >
          导入 SSH 配置
        </button>
      </div>
      {importWarnings.map((warning, i) => (
        <p className="hint" role="status" key={i}>
          {warning}
        </p>
      ))}
      {resources.map((r) => (
        <article className="resource" key={r.id}>
          <div>
            <Server size={20} />
            <span>
              <strong>{r.name || r.host}</strong>
              <small>
                {r.username ? `${r.username}@` : ""}
                {r.host}:{r.port || 22}
              </small>
            </span>
            <button onClick={() => edit(r)}>编辑</button>
            <button
              aria-label={`删除资源 ${r.name}`}
              onClick={() =>
                run("resources.remove", { id: r.id }).catch(() => {})
              }
            >
              <Trash2 size={15} />
            </button>
          </div>
          {project && (
            <label className="check">
              <input
                type="checkbox"
                checked={selected.includes(r.id)}
                onChange={(e) =>
                  run("project.resources", {
                    id: project.id,
                    resourceIds: e.target.checked
                      ? [...selected, r.id]
                      : selected.filter((id) => id !== r.id),
                  }).catch(() => {})
                }
              />
              提供给 {project.name}
            </label>
          )}
        </article>
      ))}
      {!resources.length && (
        <p className="empty-text">尚未登记资源。需要远端机器时再添加即可。</p>
      )}
      {editing && (
        <form
          className="resource-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setSaving(true);
            try {
              const resource = { ...form, port: Number(form.port) };
              if (!resource.password) delete resource.password;
              if (editing === "new") delete resource.id;
              await run("resources.save", { resource });
              setEditing(null);
              setForm({});
            } catch (e) {
              onError(message(e));
            } finally {
              setSaving(false);
            }
          }}
        >
          <h3>{editing === "new" ? "添加资源" : "编辑资源"}</h3>
          {[
            ["name", "机器别名", "text"],
            ["host", "主机 / IP", "text"],
            ["port", "端口", "number"],
            ["username", "用户名", "text"],
            ["keyPath", "密钥文件路径", "text"],
            [
              "password",
              form.hasPassword ? "密码（留空保留已有密码）" : "密码",
              "password",
            ],
          ].map(([key, label, type]) => (
            <label key={key}>
              {label}
              <input
                autoComplete={key === "password" ? "new-password" : "off"}
                type={type}
                required={key === "host" || key === "name"}
                value={form[key] || ""}
                min={key === "port" ? 1 : undefined}
                max={key === "port" ? 65535 : undefined}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
          <label>
            备注
            <textarea
              value={form.notes || ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </label>
          <p className="hint">密码通过本机安全存储保存，不写入目标文件。</p>
          <div className="toolbar">
            <button type="submit" className="primary" disabled={saving}>
              保存资源
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setForm({});
              }}
            >
              取消
            </button>
          </div>
        </form>
      )}
    </>
  );
}
function Preferences({ settings, run }) {
  const [form, setForm] = useState(settings),
    [notificationResult, setNotificationResult] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run("settings.save", { settings: form }).catch(() => {});
      }}
    >
      <h3>每日提醒</h3>
      <p className="hint">在本机时间提醒仍在运行或自动重试的项目。</p>
      <label className="check">
        <input
          type="checkbox"
          checked={!!form.notificationsEnabled}
          onChange={(e) =>
            setForm({ ...form, notificationsEnabled: e.target.checked })
          }
        />
        启用系统通知
      </label>
      <label>
        提醒时刻
        <input
          type="time"
          value={form.notificationTime || "18:00"}
          onChange={(e) =>
            setForm({ ...form, notificationTime: e.target.value })
          }
        />
      </label>
      <button
        type="button"
        onClick={() =>
          run("notifications.test")
            .then((result) =>
              setNotificationResult(
                result.message || result.status || "通知请求已提交",
              ),
            )
            .catch(() => {})
        }
      >
        测试系统通知
      </button>
      {settings.notificationError && (
        <p className="data-warning" role="alert">
          {message(settings.notificationError)}
        </p>
      )}
      {notificationResult && (
        <p className="hint" role="status">
          {notificationResult}
        </p>
      )}
      <hr />
      <h3>后台与启动</h3>
      <p className="hint">
        打开新版应用后，会同步已启用的自启动入口，下次登录使用新版。
      </p>
      {settings.startupError && (
        <p className="data-warning" role="alert">
          自启动入口同步失败：{message(settings.startupError)}
        </p>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={!!form.launchAtLogin}
          onChange={(e) =>
            setForm({ ...form, launchAtLogin: e.target.checked })
          }
        />
        登录系统后启动，恢复之前的运行意图
      </label>
      <p className="hint">
        关闭主窗口后项目继续工作。暂停的项目不会因重新打开窗口而启动。完全退出请使用系统托盘菜单。
      </p>
      <button className="primary" type="submit">
        保存设置
      </button>
    </form>
  );
}

function ChangeDirectory({ project, run, hasUnsaved, done }) {
  const [root, setRoot] = useState(project.root);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState("");
  const choose = async () => {
    setPending(true);
    try {
      const selected = await run("project.pick", { create: false });
      if (selected)
        setRoot(typeof selected === "string" ? selected : selected.root);
    } catch (error) {
      setFailure(message(error));
    } finally {
      setPending(false);
    }
  };
  return (
    <form
      className="modal-body directory-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (hasUnsaved || pending) return;
        setPending(true);
        setFailure("");
        try {
          const changed = await run("project.directory.change", {
            id: project.id,
            root: root.trim(),
          });
          done(changed.directoryWarnings || []);
        } catch (error) {
          setFailure(message(error));
        } finally {
          setPending(false);
        }
      }}
    >
      <label>
        原目录<output className="directory-original">{project.root}</output>
      </label>
      <label>
        新目录
        <input
          aria-label="新项目目录"
          value={root}
          disabled={pending}
          onChange={(event) => setRoot(event.target.value)}
        />
      </label>
      <button
        type="button"
        aria-label="选择新的项目目录"
        disabled={pending}
        onClick={choose}
      >
        <Folder size={16} />
        选择目录
      </button>
      <p className="hint directory-explanation">
        保留累计运行时间、已发布目标、资源和项目记录。目标与进度文件会复制到新目录缺失的位置；同名文件内容不同会报错，不会覆盖。
      </p>
      <p className="hint">
        更改后使用新会话。正在运行的项目自动继续，已暂停的项目保持暂停。
      </p>
      {hasUnsaved && (
        <p className="data-warning">请先保存目标草稿并解决编辑冲突。</p>
      )}
      {failure && (
        <p className="data-warning" role="alert">
          {failure}
        </p>
      )}
      <button
        type="submit"
        className="primary wide"
        disabled={
          pending || hasUnsaved || !root.trim() || root.trim() === project.root
        }
      >
        确认更改
      </button>
    </form>
  );
}
