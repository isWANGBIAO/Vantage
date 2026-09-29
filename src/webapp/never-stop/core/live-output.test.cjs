const test = require("node:test");
const assert = require("node:assert/strict");
const {
  parseDisplayEvent,
  sanitizeOutput,
  stderrEntry,
  createStderrReader,
  BoundedOutput,
} = require("./live-output.cjs");

test("Claude visible assistant, tool use and tool results exclude user and reasoning contents", () => {
  assert.deepEqual(
    parseDisplayEvent({
      type: "assistant",
      message: {
        content: [
          { type: "thinking", thinking: "NEVER_THINKING" },
          { type: "text", text: "Checking files." },
          {
            type: "tool_use",
            name: "Bash",
            input: {
              command: "npm test",
              password: "NEVER_PASS",
              prompt: "NEVER_PROMPT",
            },
          },
        ],
      },
    }).map((x) => x.kind),
    ["assistant", "tool"],
  );
  const result = parseDisplayEvent({
    type: "user",
    message: {
      content: [
        { type: "text", text: "NEVER_USER_GOAL" },
        {
          type: "tool_result",
          tool_use_id: "tool1",
          content: [
            { type: "text", text: "3 tests passed" },
            { type: "image", source: { data: "NEVER_IMAGE" } },
          ],
        },
      ],
    },
  });
  assert.deepEqual(result, [{ kind: "result", text: "3 tests passed" }]);
  const entries = parseDisplayEvent({
    type: "assistant",
    message: {
      content: [
        {
          type: "tool_use",
          name: "Bash",
          input: {
            command: "npm test",
            password: "NEVER_PASS",
            prompt: "NEVER_PROMPT",
          },
        },
      ],
    },
  });
  assert.ok(!JSON.stringify(entries).includes("NEVER_"));
  assert.deepEqual(
    parseDisplayEvent({ type: "system", prompt: "private" }),
    [],
  );
  assert.deepEqual(
    parseDisplayEvent({
      type: "stream_event",
      event: {
        type: "content_block_delta",
        delta: { type: "thinking_delta", thinking: "private" },
      },
    }),
    [],
  );
  assert.deepEqual(parseDisplayEvent({ type: "unknown", text: "private" }), []);
});
test("Codex official item shapes yield visible commands, results, file changes and MCP summaries", () => {
  assert.deepEqual(
    parseDisplayEvent({
      type: "item.completed",
      item: { type: "agent_message", text: "Finished checking." },
    }),
    [{ kind: "assistant", text: "Finished checking." }],
  );
  assert.deepEqual(
    parseDisplayEvent({
      type: "item.completed",
      item: { type: "reasoning", text: "PRIVATE" },
    }),
    [],
  );
  const command = parseDisplayEvent({
    type: "item.completed",
    item: {
      type: "command_execution",
      command: "node --test",
      aggregated_output: "passed",
      exit_code: 0,
      status: "completed",
    },
  });
  assert.deepEqual(
    command.map((x) => x.kind),
    ["tool", "result"],
  );
  assert.match(command[1].text, /passed/);
  assert.match(
    parseDisplayEvent({
      type: "item.completed",
      item: {
        type: "file_change",
        changes: [{ path: "src/a.js", kind: "update" }],
        status: "completed",
      },
    })[0].text,
    /src\/a.js/,
  );
  const mcp = parseDisplayEvent({
    type: "item.completed",
    item: {
      type: "mcp_tool_call",
      server: "local",
      tool: "lookup",
      arguments: { query: "safe", api_key: "NEVER_KEY" },
      result: {
        content: [{ type: "text", text: "found" }],
        structuredContent: { secret: "NEVER_SECRET" },
      },
      status: "completed",
    },
  });
  assert.ok(mcp.some((x) => x.text.includes("found")));
  assert.ok(!JSON.stringify(mcp).includes("NEVER_"));
  assert.equal(
    parseDisplayEvent({ type: "turn.failed", error: { message: "failure" } })[0]
      .kind,
    "error",
  );
});
test("sanitization masks named, JSON, bearer, url and private-key secrets before truncation", () => {
  const input =
    '\x1b[31mtext\x1b[0m\x00\x07 {"password":"spaced password","api_key":"json-key","nested":{"access_token":"nested-token"}} Authorization: Bearer bearer-token\nhttps://user:url-password@host/path?token=url-token&ok=yes\nPRIVATE_EXACT\n-----BEGIN OPENSSH PRIVATE KEY-----\nmultiline-secret\n-----END OPENSSH PRIVATE KEY-----\n';
  const clean = sanitizeOutput(input, ["PRIVATE_EXACT"]);
  for (const secret of [
    "spaced password",
    "json-key",
    "nested-token",
    "bearer-token",
    "url-password",
    "url-token",
    "PRIVATE_EXACT",
    "multiline-secret",
  ])
    assert.ok(!clean.includes(secret), secret);
  assert.ok(!/[\x00\x07\x1b]/.test(clean));
  assert.ok(sanitizeOutput("x".repeat(10000)).length <= 4000);
  assert.ok(
    !sanitizeOutput("a".repeat(3990) + "edge-secret", ["edge-secret"]).includes(
      "edge-se",
    ),
  );
  assert.match(stderrEntry("oops")[0].text, /oops/);
});
test("stderr reader joins fragmented secrets and suppresses multiline key bodies", () => {
  const entries = [];
  const read = createStderrReader((items) => entries.push(...items));
  read(Buffer.from('password="split'));
  read(Buffer.from(' secret"\n-----BEGIN PRIVATE KEY-----\n'));
  read(Buffer.from("SHOULD_NOT_APPEAR\n-----END PRIVATE KEY-----\nplain"));
  read.flush();
  const text = JSON.stringify(entries);
  assert.ok(!text.includes("split"));
  assert.ok(!text.includes("SHOULD_NOT_APPEAR"));
  assert.ok(text.includes("plain"));
});
test("bounded output provides incremental cursors, drops old entries, and never reuses sequence after clear", () => {
  const output = new BoundedOutput({
    maxEntries: 3,
    maxBytes: 2000,
    maxTotalBytes: 5000,
    now: () => "2026-09-12T10:00:00Z",
  });
  output.append("a", [
    { kind: "assistant", text: "one" },
    { kind: "tool", text: "two" },
    { kind: "result", text: "three" },
    { kind: "status", text: "four" },
  ]);
  assert.equal(output.read("a").entries.length, 3);
  assert.equal(output.read("a").dropped, 1);
  const cursor = output.read("a").cursor;
  assert.equal(output.read("a", { after: cursor }).entries.length, 0);
  output.clear("a");
  output.append("a", [{ kind: "error", text: "password=should-hide" }]);
  assert.ok(output.read("a").cursor > cursor);
  assert.ok(!output.read("a").entries[0].text.includes("should-hide"));
  output.remove("a");
  assert.deepEqual(output.read("a").entries, []);
});
test("global memory pressure evicts oldest projects and per-item/per-batch limits are enforced", () => {
  const output = new BoundedOutput({
    maxEntries: 300,
    maxBytes: 262144,
    maxTotalBytes: 16000,
  });
  for (let i = 0; i < 5000; i++)
    output.append(`p${i % 20}`, [
      { kind: "assistant", text: "中".repeat(5000) },
    ]);
  const entries = Array.from(
    { length: 20 },
    (_, i) => output.read(`p${i}`).entries,
  ).flat();
  assert.ok(entries.every((x) => x.text.length <= 4000));
  assert.ok(
    entries.reduce((sum, x) => sum + Buffer.byteLength(JSON.stringify(x)), 0) <=
      16000,
  );
  const many = parseDisplayEvent({
    type: "assistant",
    message: {
      content: Array.from({ length: 1000 }, () => ({
        type: "text",
        text: "visible",
      })),
    },
  });
  assert.ok(many.length <= 32);
});
test("long plain output is sanitized without quadratic processing", () => {
  const begin = performance.now();
  const result = sanitizeOutput("a".repeat(65536));
  assert.ok(result.length <= 4000);
  assert.ok(
    performance.now() - begin < 1000,
    "64 KiB plain output must not block the worker for a second",
  );
});
test("unfinished quoted credential values do not leak trailing words", () => {
  for (const value of [
    'password="unfinished secret words',
    "api_key='unfinished secret words",
    '{"authorization":"unfinished secret words',
  ]) {
    const clean = sanitizeOutput(value);
    assert.ok(!clean.includes("secret words"), clean);
  }
});
