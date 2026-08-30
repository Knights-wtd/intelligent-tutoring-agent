import type { RuntimeEventEnvelope, RuntimeStartRequest } from "@textbook-agent/agent-protocol";

import { ClaudeProvider, DEFAULT_CLAUDE_SYSTEM_PROMPT } from "../src/providers/claude/ClaudeProvider";
import type { ClaudeSdkAdapter, ClaudeSdkQuery } from "../src/providers/claude/ClaudeProvider";
import type { ProviderStartRequest } from "../src/providers/types";

function makeRequest(overrides: Partial<ProviderStartRequest> = {}): ProviderStartRequest {
  return {
    session_id: "app-session",
    turn_id: "turn-1",
    input: [{ type: "text", text: "hello" }],
    workspace_roots: ["C:\\vault", "D:\\shared"],
    provider: "claude",
    model: "claude-sonnet",
    permission_mode: "bypassPermissions",
    capability: "signed-capability",
    callback_url: "http://127.0.0.1/events",
    idempotency_key: "start-1",
    ...overrides,
  };
}

function queryFrom(messages: readonly Record<string, unknown>[]) {
  const generator = (async function* () {
    for (const message of messages) yield message;
  })() as unknown as ClaudeSdkQuery;
  generator.interrupt = jest.fn(async () => undefined);
  generator.rewindFiles = jest.fn(async () => ({ canRewind: true, filesChanged: [] }));
  return generator;
}

describe("ClaudeProvider", () => {
  it("adapts the SDK with persistent resume, all workspace roots, and bypassPermissions", async () => {
    const calls: Array<{ prompt: unknown; options: Record<string, unknown> }> = [];
    const query = queryFrom([
      { type: "system", subtype: "init", session_id: "native-1" },
      {
        type: "stream_event",
        session_id: "native-1",
        event: { type: "content_block_delta", delta: { type: "text_delta", text: "answer" } },
      },
      { type: "result", subtype: "success", session_id: "native-1", usage: { input_tokens: 2, output_tokens: 3 } },
    ]);
    const sdk: ClaudeSdkAdapter = {
      query: (params) => {
        calls.push(params);
        return query;
      },
      forkSession: jest.fn(async () => ({ sessionId: "fork-native" })),
    };
    const provider = new ClaudeProvider({ sdkLoader: async () => sdk, uuid: () => "event-id", executablePath: "C:\\tools\\claude.exe" });

    const events: RuntimeEventEnvelope[] = [];
    for await (const event of provider.start(makeRequest({
      native_session_id: "native-1",
      mcp_servers: { textbook: { command: "textbook-mcp" } },
      skills: ["review", "citations"],
      subagents: { researcher: { description: "Research public sources", prompt: "Research" } },
    }), new AbortController().signal)) {
      events.push(event);
    }

    expect(calls).toHaveLength(1);
    expect(calls[0].prompt).toBe("hello");
    expect(calls[0].options).toMatchObject({
      cwd: "C:\\vault",
      additionalDirectories: ["D:\\shared"],
      model: "claude-sonnet",
      pathToClaudeCodeExecutable: "C:\\tools\\claude.exe",
      permissionMode: "bypassPermissions",
      allowDangerouslySkipPermissions: true,
      persistSession: true,
      resume: "native-1",
      includePartialMessages: true,
      enableFileCheckpointing: true,
      mcpServers: { textbook: { command: "textbook-mcp" } },
      skills: ["review", "citations"],
      agents: { researcher: { description: "Research public sources", prompt: "Research" } },
    });
    expect(String(calls[0].options.systemPrompt)).toBe(DEFAULT_CLAUDE_SYSTEM_PROMPT);
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).toContain("Vault");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).toContain("模型知识");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).toContain("公开 Web");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).toContain("来源");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).toContain("不确定");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).not.toContain("无教材禁止回答");
    expect(DEFAULT_CLAUDE_SYSTEM_PROMPT).not.toContain("仅依据" + "教材");
    expect(events.map(item => item.event_type)).toEqual(["turn_started", "model_text_delta", "usage", "session_state"]);
    expect(events[0].payload).toMatchObject({ native_session_id: "native-1", permission_mode: "bypassPermissions" });
  });

  it("normalizes SDK user messages to payload.text", async () => {
    const query = queryFrom([
      { type: "system", subtype: "init", session_id: "native-1" },
      {
        type: "user",
        session_id: "native-1",
        message: {
          role: "user",
          content: [
            { type: "text", text: "第一段" },
            { type: "image", source: { type: "base64", data: "not-emitted" } },
            { type: "text", text: "第二段" },
          ],
        },
      },
    ]);
    const sdk: ClaudeSdkAdapter = {
      query: () => query,
      forkSession: async () => ({ sessionId: "fork-native" }),
    };
    const provider = new ClaudeProvider({ sdkLoader: async () => sdk });

    const events: RuntimeEventEnvelope[] = [];
    for await (const event of provider.start(makeRequest(), new AbortController().signal)) {
      events.push(event);
    }

    const userMessage = events.find(event => event.event_type === "user_message");
    expect(userMessage?.payload).toEqual({ text: "第一段\n第二段" });
  });

  it("stops, rewinds, forks, and reports health through the SDK boundary", async () => {
    const query = queryFrom([{ type: "system", subtype: "init", session_id: "native-1" }]);
    const forkSession = jest.fn(async () => ({ sessionId: "fork-native" }));
    const sdk: ClaudeSdkAdapter = { query: () => query, forkSession };
    const provider = new ClaudeProvider({ sdkLoader: async () => sdk });
    for await (const _event of provider.start(makeRequest(), new AbortController().signal)) { /* drain */ }

    await provider.stop("app-session");
    expect(query.interrupt).toHaveBeenCalledTimes(1);
    await provider.rewind("app-session", "checkpoint-1");
    expect(query.rewindFiles).toHaveBeenCalledWith("checkpoint-1", { dryRun: false });
    await expect(provider.fork("app-session", "checkpoint-1")).resolves.toEqual({ native_session_id: "fork-native" });
    expect(forkSession).toHaveBeenCalledWith("native-1", { upToMessageId: "checkpoint-1", dir: "C:\\vault" });
    await expect(provider.health()).resolves.toEqual({ status: "ok" });
  });

  it("rejects requests that do not carry the fixed bypass permission mode", async () => {
    const sdk: ClaudeSdkAdapter = {
      query: () => queryFrom([]),
      forkSession: async () => ({ sessionId: "fork-native" }),
    };
    const provider = new ClaudeProvider({ sdkLoader: async () => sdk });
    const request = { ...makeRequest(), permission_mode: "default" } as unknown as RuntimeStartRequest;
    const consume = async () => {
      for await (const _event of provider.start(request, new AbortController().signal)) { /* drain */ }
    };
    await expect(consume()).rejects.toMatchObject({ code: "invalid_permission_mode" });
  });
});
