"use strict";
const fs = require("node:fs/promises");
const path = require("node:path");
const { StringDecoder } = require('node:string_decoder');
function createLineReader(onLine, limit = 65536) {
  const decoder = new StringDecoder('utf8');
  let pending = "",
    dropping = false;
  const readText = (text) => {
    for (const part of text.split(/(?<=\n)/)) {
      const ends = part.endsWith("\n");
      if (!dropping) {
        if (pending.length + part.length > limit) {
          pending = "";
          dropping = true;
        } else pending += part;
      }
      if (ends) {
        if (!dropping) onLine(pending.trimEnd());
        pending = "";
        dropping = false;
      }
    }
  };
  const read = (chunk) => readText(typeof chunk === 'string' ? chunk : decoder.write(chunk));
  read.flush = () => {
    readText(decoder.end());
    if (pending && !dropping) onLine(pending.trimEnd());
    pending = '';
    dropping = false;
  };
  return read;
}
function redact(text) {
  return String(text)
    .replace(
      /-----BEGIN [\s\S]*?PRIVATE KEY-----[\s\S]*/g,
      "[private key redacted]",
    )
    .replace(
      /\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+/g,
      "[credential redacted]",
    )
    .replace(
      /((?:authorization|password|passwd|token|api[_-]?key|secret)\s*[=:]\s*)[^\s,;]+/gi,
      "$1[redacted]",
    )
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/g, "$1[redacted]@")
    .slice(0, 1000);
}
async function discoverExecutable(backend) {
  if (!["codex", "claude"].includes(backend))
    throw Error("Unsupported backend");
  const suffixes = process.platform === "win32" ? [".exe"] : [""];
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    for (const suffix of suffixes) {
      const candidate = path.join(dir, backend + suffix);
      try {
        await fs.access(candidate);
        return candidate;
      } catch {}
    }
  }
  throw Error(
    `${backend} executable not found on PATH; install/configure the existing CLI first` +
      (process.platform === "win32"
        ? "; this demo currently requires a native .exe and does not execute npm .cmd shims"
        : ""),
  );
}
function buildInvocation(project, command) {
  const { backend, sessionId } = project;
  if (backend === "codex")
    return {
      backend,
      command,
      args: sessionId
        ? ["exec", "resume", "--json", "--skip-git-repo-check", sessionId, "-"]
        : ["exec", "--json", "--skip-git-repo-check", "-"],
    };
  if (backend === "claude")
    return {
      backend,
      command,
      args: [
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        ...(sessionId ? ["--resume", sessionId] : []),
      ],
    };
  throw Error("Unsupported backend");
}
async function adapterFactory(project) {
  return buildInvocation(project, await discoverExecutable(project.backend));
}
function parseEvent(line) {
  let e;
  try {
    e = JSON.parse(line);
  } catch {
    return null;
  }
  if (e?.type === 'stream_event' && e.event?.type === 'error') e = e.event;
  if (!e || typeof e !== 'object') return null;
  if (e.type === "thread.started" && typeof e.thread_id === "string")
    return { type: "session", id: e.thread_id.slice(0, 200) };
  if (
    e.type === "system" &&
    e.subtype === "init" &&
    typeof e.session_id === "string"
  )
    return { type: "session", id: e.session_id.slice(0, 200) };
  if (
    e.type === "error" ||
    e.type === "turn.failed" ||
    (e.type === "result" && e.is_error)
  )
    return {
      type: "error",
      message: redact(
        e.message ||
          e.error?.message ||
          (Array.isArray(e.errors)
            ? e.errors.join("; ")
            : "CLI reported execution failure"),
      ),
    };
  return null;
}
module.exports = {
  adapterFactory,
  buildInvocation,
  discoverExecutable,
  createLineReader,
  parseEvent,
  redact,
};
