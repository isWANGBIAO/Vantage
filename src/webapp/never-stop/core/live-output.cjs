"use strict";
const { stripVTControlCharacters } = require("node:util");
const { StringDecoder } = require("node:string_decoder");
const MAX_TEXT = 4000;
const MAX_INPUT = 1024 * 1024;
const MAX_BATCH = 32;
const KINDS = new Set(["assistant", "tool", "result", "error", "status"]);
const PRIVATE_FIELD =
  /(?:password|passwd|passphrase|secret|token|api[_-]?key|authorization|cookie|private[_-]?key|client[_-]?secret|credential)/i;
const HIDDEN_FIELD =
  /^(?:system|system_prompt|prompt|instructions|developer_instructions|input_user_goal|user_goal|reasoning|thinking|signature)$/i;

function sanitizeOutput(value, secrets = []) {
  if (typeof value !== "string") return "";
  if (value.length > MAX_INPUT) return "[输出超过显示解析上限]";
  let text = stripVTControlCharacters(value).replace(
    /[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g,
    "",
  );
  for (const secret of secrets) {
    if (typeof secret === "string" && secret.length > 0)
      text = text.split(secret).join("[已隐藏]");
  }
  text = text
    .replace(
      /-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\r\n]*PRIVATE KEY-----|$)/g,
      "[私钥已隐藏]",
    )
    .replace(
      /\b(?:sk-[a-zA-Z0-9_-]+|ghp_[a-zA-Z0-9_]+|github_pat_[a-zA-Z0-9_]+|AKIA[A-Z0-9]{16})\b/g,
      "[凭据已隐藏]",
    )
    .replace(
      /(\b(?:Authorization|Proxy-Authorization)\s*["']?\s*[:=]\s*["']?)(?:Bearer|Basic)\s+[^\s"',;]+/gi,
      "$1[已隐藏]",
    )
    .replace(/(\bBearer\s+)[a-zA-Z0-9._~+\/-]+=*/gi, "$1[已隐藏]")
    .replace(
      /(\b[a-z][a-z0-9+.-]*:\/\/)[^\s/@]*:[^\s/@]*@/gi,
      "$1[凭据已隐藏]@",
    )
    .replace(
      /((?:["']?\b[\w-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|authorization|cookie|private[_-]?key|credential)[\w-]*["']?)\s*[:=]\s*)("(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|[^\s,;&}\]]+)/gi,
      "$1[已隐藏]",
    );
  return text.length > MAX_TEXT
    ? text.slice(0, MAX_TEXT - 8) + "…[已截断]"
    : text;
}
function displayData(value, secrets, depth = 0, budget = { left: 256 }) {
  if (budget.left-- <= 0 || depth > 8) return "[结构已截断]";
  if (typeof value === "string") return sanitizeOutput(value, secrets);
  if (value === null || typeof value === "boolean" || typeof value === "number")
    return value;
  if (Array.isArray(value))
    return value
      .slice(0, MAX_BATCH)
      .map((item) => displayData(item, secrets, depth + 1, budget));
  if (value && typeof value === "object") {
    const result = Object.create(null);
    for (const key of Object.keys(value).slice(0, MAX_BATCH)) {
      if (HIDDEN_FIELD.test(key)) continue;
      result[sanitizeOutput(key, secrets)] = PRIVATE_FIELD.test(key)
        ? "[已隐藏]"
        : displayData(value[key], secrets, depth + 1, budget);
    }
    return result;
  }
  return undefined;
}
function dataText(value, secrets) {
  const safe = displayData(value, secrets);
  return safe === undefined
    ? ""
    : typeof safe === "string"
      ? safe
      : JSON.stringify(safe);
}
function contentText(content, secrets) {
  if (typeof content === "string") return sanitizeOutput(content, secrets);
  if (!Array.isArray(content)) return "";
  return content
    .slice(0, MAX_BATCH)
    .filter((block) => block?.type === "text" && typeof block.text === "string")
    .map((block) => sanitizeOutput(block.text, secrets))
    .join("\n");
}

// Allowlist the public event fields in Claude stream-json and Codex exec --json.
// Raw partial text is never displayed: a credential can span arbitrary chunks.
// createDisplayParser adds metadata-only activity while complete blocks are
// sanitized here, once, using Claude's normal assistant events.
function parseDisplayEvent(line, secrets = []) {
  let event = line;
  if (typeof line === "string") {
    if (line.length > MAX_INPUT)
      return [{ kind: "status", text: "[单条事件超过显示解析上限]" }];
    try {
      event = JSON.parse(line);
    } catch {
      return [];
    }
  }
  if (!event || typeof event !== "object" || Array.isArray(event)) return [];
  const entries = [];
  const add = (kind, text) => {
    if (entries.length >= MAX_BATCH) return;
    const clean = sanitizeOutput(text, secrets);
    if (clean.trim()) entries.push({ kind, text: clean });
  };
  if (event.type === "assistant" && Array.isArray(event.message?.content)) {
    for (const block of event.message.content.slice(0, MAX_BATCH)) {
      if (block?.type === "text") add("assistant", block.text);
      else if (block?.type === "tool_use")
        add(
          "tool",
          `${sanitizeOutput(block.name || "工具", secrets)}\n${dataText(block.input, secrets)}`,
        );
    }
  } else if (event.type === "user" && Array.isArray(event.message?.content)) {
    for (const block of event.message.content.slice(0, MAX_BATCH)) {
      if (block?.type === "tool_result")
        add(
          block.is_error ? "error" : "result",
          contentText(block.content, secrets),
        );
    }
  } else if (
    ["item.started", "item.updated", "item.completed"].includes(event.type)
  ) {
    const item = event.item;
    if (!item || typeof item !== "object") return [];
    if (item.type === "agent_message") add("assistant", item.text);
    else if (item.type === "command_execution") {
      add("tool", item.command);
      if (item.aggregated_output)
        add(
          item.status === "failed" ? "error" : "result",
          item.aggregated_output,
        );
      else if (event.type === "item.completed")
        add(
          "status",
          `命令结束${Number.isInteger(item.exit_code) ? `（退出码 ${item.exit_code}）` : ""}`,
        );
    } else if (item.type === "file_change") {
      const changes = Array.isArray(item.changes)
        ? item.changes.slice(0, MAX_BATCH)
        : [];
      add(
        item.status === "failed" ? "error" : "tool",
        `文件变更${item.status === "failed" ? "失败" : ""}\n${changes.map((change) => `${sanitizeOutput(String(change.kind || ""), secrets)} ${sanitizeOutput(String(change.path || ""), secrets)}`).join("\n")}`,
      );
    } else if (item.type === "mcp_tool_call") {
      add(
        "tool",
        `${sanitizeOutput(item.server || "", secrets)}/${sanitizeOutput(item.tool || "工具", secrets)}\n${dataText(item.arguments, secrets)}`,
      );
      if (item.result) {
        const text = contentText(item.result.content, secrets);
        if (text) add("result", text);
        if (item.result.structuredContent)
          add("result", dataText(item.result.structuredContent, secrets));
      }
      if (item.error)
        add(
          "error",
          typeof item.error === "string" ? item.error : item.error.message,
        );
    } else if (item.type === "error") add("error", item.message);
  } else if (event.type === "error" || event.type === "turn.failed") {
    add(
      "error",
      event.message ||
        event.error?.message ||
        (typeof event.error === "string" ? event.error : "Agent 执行失败"),
    );
  } else if (event.type === "result") {
    if (event.is_error)
      add(
        "error",
        Array.isArray(event.errors)
          ? event.errors
              .filter((x) => typeof x === "string")
              .slice(0, MAX_BATCH)
              .join("\n")
          : event.result || "Agent 执行失败",
      );
    else add("status", "本轮调用结束");
  } else if (event.type === "turn.completed") add("status", "本轮调用结束");
  return entries;
}

function createDisplayParser({ secrets = [], now = () => performance.now() } = {}) {
  let phase = '', characters = 0, lastDisplay = -Infinity;
  const activity = (nextPhase, length = 0) => {
    const changed = nextPhase !== phase;
    if (changed) characters = 0;
    phase = nextPhase;
    characters = Math.min(Number.MAX_SAFE_INTEGER, characters + length);
    const time = now();
    if (!changed && time - lastDisplay < 5000) return [];
    lastDisplay = time;
    const labels = {
      thinking: '模型正在思考（思考内容不展示）',
      text: '正在生成回复（完整段落脱敏后显示）',
      tool: '正在生成工具参数（完整参数脱敏后显示）',
      compacting: '正在压缩上下文',
    };
    return [{ kind: 'status', text: `${labels[phase]}${characters ? ` · 已接收 ${characters} 字符` : ''}` }];
  };
  return (line) => {
    let event = line;
    if (typeof line === 'string') {
      if (line.length > MAX_INPUT) return parseDisplayEvent(line, secrets);
      try { event = JSON.parse(line); } catch { return []; }
    }
    if (!event || typeof event !== 'object') return [];
    if (event.type === 'system' && event.subtype === 'status' && event.status === 'compacting') return activity('compacting');
    if (event.type === 'system' && event.subtype === 'compact_boundary') {
      phase = ''; characters = 0;
      return [{ kind: 'status', text: '上下文压缩完成，继续调用' }];
    }
    if (event.type !== 'stream_event') return parseDisplayEvent(event, secrets);
    const raw = event.event;
    if (!raw || typeof raw !== 'object') return [];
    if (raw.type === 'message_start') { phase = ''; characters = 0; }
    if (raw.type === 'error') return parseDisplayEvent(raw, secrets);
    if (raw.type === 'content_block_start') {
      const type = raw.content_block?.type;
      if (type === 'thinking') return activity('thinking');
      if (type === 'text') return activity('text');
      if (type === 'tool_use') return activity('tool');
    }
    if (raw.type === 'content_block_delta') {
      const delta = raw.delta;
      const fields = { thinking_delta: ['thinking', 'thinking'], text_delta: ['text', 'text'], input_json_delta: ['tool', 'partial_json'] };
      const field = fields[delta?.type];
      if (field && typeof delta[field[1]] === 'string') return activity(field[0], delta[field[1]].length);
    }
    return [];
  };
}
function stderrEntry(text, secrets = []) {
  // Claude emits this catalog diagnostic on stderr even for successful calls.
  // Recognize the complete known shape, never a substring of an actual error.
  if (typeof text === 'string' && text.length <= MAX_TEXT) {
    const prefix = '[claude-code:unrecognized_model] ';
    const line = text.trim();
    if (line.startsWith(prefix)) {
      try {
        const diagnostic = JSON.parse(line.slice(prefix.length));
        if (diagnostic && Object.keys(diagnostic).length === 2 &&
            ['model', 'query_source'].every(key =>
              typeof diagnostic[key] === 'string' && diagnostic[key].trim() &&
              diagnostic[key].length <= 256 && !/[\r\n\x00-\x1f\x7f]/.test(diagnostic[key]))) {
          return [{ kind: 'status', text: sanitizeOutput(
            `模型兼容性提示：${diagnostic.model} 不在 Claude Code 内置模型列表中；此提示本身不表示调用失败。`, secrets,
          ) }];
        }
      } catch { /* Unknown or mixed stderr remains an error below. */ }
    }
  }
  const clean = sanitizeOutput(text, secrets);
  return clean.trim() ? [{ kind: "error", text: clean }] : [];
}
function createStderrReader(onEntries, secrets = []) {
  const decoder = new StringDecoder("utf8");
  let pending = "",
    dropping = false,
    privateKey = false;
  const emit = (line) => {
    if (/-----BEGIN [^-\r\n]*PRIVATE KEY-----/.test(line)) {
      privateKey = !/-----END [^-\r\n]*PRIVATE KEY-----/.test(line);
      onEntries([{ kind: "error", text: "[私钥已隐藏]" }]);
      return;
    }
    if (privateKey) {
      if (/-----END [^-\r\n]*PRIVATE KEY-----/.test(line)) privateKey = false;
      return;
    }
    onEntries(stderrEntry(line, secrets));
  };
  const readText = (text) => {
    for (const part of text.split(/(?<=\n)/)) {
      const ends = part.endsWith("\n");
      if (!dropping) {
        if (pending.length + part.length > 65536) {
          pending = "";
          dropping = true;
        } else pending += part;
      }
      if (ends) {
        if (!dropping) emit(pending);
        pending = "";
        dropping = false;
      }
    }
  };
  const read = (chunk) =>
    readText(typeof chunk === "string" ? chunk : decoder.write(chunk));
  read.flush = () => {
    readText(decoder.end());
    if (pending && !dropping) emit(pending);
    pending = "";
    dropping = false;
  };
  return read;
}

class BoundedOutput {
  constructor({
    maxEntries = 300,
    maxBytes = 256 * 1024,
    maxTotalBytes = 4 * 1024 * 1024,
    maxProjects = 256,
    now = () => new Date().toISOString(),
  } = {}) {
    for (const value of [maxEntries, maxBytes, maxTotalBytes, maxProjects])
      if (!Number.isSafeInteger(value) || value < 1)
        throw new Error("输出缓存上限必须为正整数");
    Object.assign(this, {
      maxEntries,
      maxBytes,
      maxTotalBytes,
      maxProjects,
      now,
    });
    this.projects = new Map();
    this.events = new Map();
    this.totalBytes = 0;
    this.sequence = 0;
  }
  evict(holder) {
    const state = this.projects.get(holder.projectId);
    if (!state || !this.events.delete(holder.entry.seq)) return;
    const index = state.entries.indexOf(holder);
    if (index >= 0) state.entries.splice(index, 1);
    state.bytes -= holder.bytes;
    state.dropped++;
    this.totalBytes -= holder.bytes;
  }
  append(projectId, entries) {
    if (
      typeof projectId !== "string" ||
      !projectId ||
      projectId.length > 200 ||
      !Array.isArray(entries)
    )
      return;
    let state = this.projects.get(projectId);
    if (!state) {
      if (this.projects.size >= this.maxProjects)
        this.remove(this.projects.keys().next().value);
      state = { entries: [], bytes: 0, cursor: 0, dropped: 0 };
      this.projects.set(projectId, state);
    }
    for (const input of entries.slice(0, MAX_BATCH)) {
      if (!input || !KINDS.has(input.kind)) continue;
      const text = sanitizeOutput(input.text);
      if (!text.trim()) continue;
      const entry = {
        seq: ++this.sequence,
        at: this.now(),
        kind: input.kind,
        text,
      };
      state.cursor = entry.seq;
      const holder = {
        projectId,
        entry,
        bytes: Buffer.byteLength(JSON.stringify(entry)),
      };
      state.entries.push(holder);
      state.bytes += holder.bytes;
      this.totalBytes += holder.bytes;
      this.events.set(entry.seq, holder);
      while (
        state.entries.length > this.maxEntries ||
        state.bytes > this.maxBytes
      )
        this.evict(state.entries[0]);
      while (this.totalBytes > this.maxTotalBytes)
        this.evict(this.events.values().next().value);
    }
  }
  read(projectId, { after = 0 } = {}) {
    const state = this.projects.get(projectId);
    if (!state) return { entries: [], cursor: 0, dropped: 0 };
    const since = Number.isSafeInteger(after) && after >= 0 ? after : 0;
    return {
      entries: state.entries
        .filter((holder) => holder.entry.seq > since)
        .map((holder) => ({ ...holder.entry })),
      cursor: state.cursor,
      dropped: state.dropped,
    };
  }
  clear(projectId) {
    const state = this.projects.get(projectId);
    if (!state) return;
    for (const holder of [...state.entries]) this.evict(holder);
  }
  remove(projectId) {
    this.clear(projectId);
    this.projects.delete(projectId);
  }
}
module.exports = {
  parseDisplayEvent,
  createDisplayParser,
  sanitizeOutput,
  stderrEntry,
  createStderrReader,
  BoundedOutput,
};
