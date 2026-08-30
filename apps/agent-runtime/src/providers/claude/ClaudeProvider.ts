import { randomUUID } from "node:crypto";

import type { RuntimeEventEnvelope, RuntimeEventType } from "@textbook-agent/agent-protocol";

import type { AgentProvider, ProviderHealth, ProviderStartRequest } from "../types";

/**
 * Host adapter for the Claude Agent SDK 0.3.226.  The option projection follows
 * Claudian's vendored ClaudeExecutionRequestEncoder and claudeColdStartQuery,
 * while keeping Obsidian-specific ProviderHost dependencies outside Runtime.
 */
export interface ClaudeSdkQuery extends AsyncIterable<Record<string, unknown>> {
  interrupt(): Promise<unknown>;
  rewindFiles(checkpointId: string, options?: { dryRun?: boolean }): Promise<{
    canRewind: boolean;
    error?: string;
    filesChanged?: unknown[];
  }>;
}

export interface ClaudeSdkAdapter {
  query(params: { prompt: unknown; options: Record<string, unknown> }): ClaudeSdkQuery;
  forkSession(sessionId: string, options?: { dir?: string; upToMessageId?: string }): Promise<{ sessionId: string }>;
}

export interface ClaudeProviderOptions {
  sdkLoader?: () => Promise<ClaudeSdkAdapter>;
  uuid?: () => string;
  now?: () => string;
  systemPrompt?: string;
  /** Explicit native Claude Code executable, useful on Windows/pnpm installations. */
  executablePath?: string;
}

interface ActiveClaudeSession {
  query: ClaudeSdkQuery;
  nativeSessionId: string | null;
  cwd: string;
  abortController: AbortController;
}

export const DEFAULT_CLAUDE_SYSTEM_PROMPT = [
  "你是知识库工作区智能体。回答时可以综合使用：用户授权的 Vault 内容、模型自身知识以及通过工具取得的公开 Web 信息。",
  "对关键事实明确标识来源类别（Vault、模型知识、公开 Web）；能给出具体文件或网页来源时一并给出。",
  "不要把推测写成事实；信息不足、来源冲突或时效性不明时，明确说明不确定性并建议验证方式。",
  "不得因为 Vault 中没有材料而拒绝使用模型知识或公开 Web，但必须遵守 capability、路径和工具安全边界。",
].join("\n");

export class InvalidPermissionModeError extends Error {
  readonly code = "invalid_permission_mode" as const;

  constructor() {
    super("ClaudeProvider requires permission_mode=bypassPermissions");
    this.name = "InvalidPermissionModeError";
  }
}

export class ClaudeProvider implements AgentProvider {
  readonly id = "claude";
  private readonly sdkLoader: () => Promise<ClaudeSdkAdapter>;
  private readonly uuid: () => string;
  private readonly now: () => string;
  private readonly systemPrompt: string;
  private readonly executablePath: string | undefined;
  private readonly active = new Map<string, ActiveClaudeSession>();
  private sdkPromise: Promise<ClaudeSdkAdapter> | undefined;

  constructor(options: ClaudeProviderOptions = {}) {
    this.sdkLoader = options.sdkLoader ?? loadDefaultSdk;
    this.uuid = options.uuid ?? randomUUID;
    this.now = options.now ?? (() => new Date().toISOString());
    this.systemPrompt = options.systemPrompt ?? DEFAULT_CLAUDE_SYSTEM_PROMPT;
    this.executablePath = options.executablePath;
  }

  async *start(request: ProviderStartRequest, signal: AbortSignal): AsyncIterable<RuntimeEventEnvelope> {
    if (request.permission_mode !== "bypassPermissions") throw new InvalidPermissionModeError();
    if (request.workspace_roots.length === 0) throw new TypeError("ClaudeProvider requires at least one workspace root");

    const sdk = await this.loadSdk();
    const abortController = new AbortController();
    const abort = () => abortController.abort(signal.reason);
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });

    const options: Record<string, unknown> = {
      cwd: request.workspace_roots[0],
      ...(request.workspace_roots.length > 1
        ? { additionalDirectories: [...request.workspace_roots.slice(1)] }
        : {}),
      model: request.model,
      ...(this.executablePath ? { pathToClaudeCodeExecutable: this.executablePath } : {}),
      systemPrompt: this.systemPrompt,
      abortController,
      permissionMode: "bypassPermissions",
      allowDangerouslySkipPermissions: true,
      persistSession: true,
      includePartialMessages: true,
      enableFileCheckpointing: true,
      ...(request.native_session_id ? { resume: request.native_session_id } : {}),
      ...(request.mcp_servers ? { mcpServers: { ...request.mcp_servers } } : {}),
      ...(request.skills ? { skills: [...request.skills] } : {}),
      ...(request.subagents ? { agents: { ...request.subagents } } : {}),
    };
    const query = sdk.query({ prompt: buildPrompt(request), options });
    const active: ActiveClaudeSession = {
      query,
      nativeSessionId: request.native_session_id ?? null,
      cwd: request.workspace_roots[0],
      abortController,
    };
    this.active.set(request.session_id, active);

    let localSequence = 0;
    let sawStreamingAssistantOutput = false;
    try {
      for await (const message of query) {
        const nativeSessionId = readString(message.session_id);
        if (nativeSessionId) active.nativeSessionId = nativeSessionId;
        const normalized = normalizeSdkMessage(message, sawStreamingAssistantOutput);
        if (message.type === "stream_event" && normalized.length > 0) {
          sawStreamingAssistantOutput = true;
        }
        for (const item of normalized) {
          localSequence += 1;
          yield createEnvelope(request, item.type, item.payload, localSequence, this.uuid, this.now);
        }
      }
    } catch (error) {
      if (!abortController.signal.aborted) throw error;
    } finally {
      signal.removeEventListener("abort", abort);
    }
  }

  async stop(sessionId: string): Promise<void> {
    const session = this.requireActive(sessionId);
    session.abortController.abort(new Error("Runtime session stopped"));
    await session.query.interrupt().catch(() => undefined);
  }

  async rewind(sessionId: string, checkpointId: string): Promise<void> {
    const session = this.requireActive(sessionId);
    const result = await session.query.rewindFiles(checkpointId, { dryRun: false });
    if (!result.canRewind) throw new Error(result.error ?? `Claude session cannot rewind to ${checkpointId}`);
  }

  async fork(sessionId: string, checkpointId: string): Promise<{ native_session_id: string }> {
    const session = this.requireActive(sessionId);
    if (!session.nativeSessionId) throw new Error(`Claude session ${sessionId} has no native session id`);
    const sdk = await this.loadSdk();
    const result = await sdk.forkSession(session.nativeSessionId, {
      upToMessageId: checkpointId,
      dir: session.cwd,
    });
    return { native_session_id: result.sessionId };
  }

  async health(): Promise<ProviderHealth> {
    try {
      await this.loadSdk();
      return { status: "ok" };
    } catch (error) {
      return { status: "unavailable", detail: errorMessage(error) };
    }
  }

  private loadSdk(): Promise<ClaudeSdkAdapter> {
    this.sdkPromise ??= this.sdkLoader();
    return this.sdkPromise;
  }

  private requireActive(sessionId: string): ActiveClaudeSession {
    const session = this.active.get(sessionId);
    if (!session) throw new Error(`Claude session ${sessionId} is not loaded in this Runtime`);
    return session;
  }
}

interface NormalizedEvent {
  type: RuntimeEventType;
  payload: Record<string, unknown>;
}

function normalizeSdkMessage(message: Record<string, unknown>, suppressAssistantContent: boolean): NormalizedEvent[] {
  const sessionId = readString(message.session_id);
  if (message.type === "system" && message.subtype === "init") {
    return [{
      type: "turn_started",
      payload: {
        native_session_id: sessionId,
        permission_mode: "bypassPermissions",
        ...(Array.isArray(message.tools) ? { tools: message.tools } : {}),
        ...(Array.isArray(message.mcp_servers) ? { mcp_servers: message.mcp_servers } : {}),
      },
    }];
  }

  if (message.type === "stream_event") {
    return normalizeStreamEvent(asRecord(message.event));
  }

  if (message.type === "assistant" && !suppressAssistantContent) {
    return normalizeContentBlocks(asRecord(message.message).content);
  }

  if (message.type === "user") {
    return [{ type: "user_message", payload: { message: message.message ?? null } }];
  }

  if (message.type === "result") {
    const events: NormalizedEvent[] = [];
    if (isRecord(message.usage)) events.push({ type: "usage", payload: { ...message.usage } });
    events.push({
      type: "session_state",
      payload: {
        state: message.subtype === "success" ? "completed" : "failed",
        native_session_id: sessionId,
        ...(typeof message.result === "string" ? { result: message.result } : {}),
        ...(typeof message.error === "string" ? { error: message.error } : {}),
      },
    });
    return events;
  }

  if (message.type === "system" && (message.subtype === "compact_boundary" || message.compact_result === "success")) {
    return [{ type: "compaction", payload: { subtype: message.subtype ?? "status" } }];
  }

  if (message.type === "system" && message.subtype === "tool_progress") {
    return [{ type: "tool_progress", payload: { ...message } }];
  }

  return [];
}

function normalizeStreamEvent(event: Record<string, unknown>): NormalizedEvent[] {
  if (event.type === "content_block_delta") {
    const delta = asRecord(event.delta);
    if (delta.type === "text_delta" && typeof delta.text === "string") {
      return [{ type: "model_text_delta", payload: { text: delta.text } }];
    }
    if ((delta.type === "thinking_delta" || delta.type === "signature_delta") && typeof delta.thinking === "string") {
      return [{ type: "thinking_delta", payload: { text: delta.thinking } }];
    }
    if (delta.type === "input_json_delta") {
      return [{ type: "tool_progress", payload: { partial_json: delta.partial_json ?? "" } }];
    }
  }
  if (event.type === "content_block_start") {
    const block = asRecord(event.content_block);
    if (block.type === "tool_use") {
      return [{
        type: "tool_started",
        payload: { tool_call_id: block.id ?? null, name: block.name ?? null, input: block.input ?? {} },
      }];
    }
  }
  return [];
}

function normalizeContentBlocks(value: unknown): NormalizedEvent[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((blockValue): NormalizedEvent[] => {
    const block = asRecord(blockValue);
    if (block.type === "text" && typeof block.text === "string") {
      return [{ type: "model_text_delta", payload: { text: block.text } }];
    }
    if (block.type === "thinking" && typeof block.thinking === "string") {
      return [{ type: "thinking_delta", payload: { text: block.thinking } }];
    }
    if (block.type === "tool_use") {
      return [{
        type: "tool_started",
        payload: { tool_call_id: block.id ?? null, name: block.name ?? null, input: block.input ?? {} },
      }];
    }
    return [];
  });
}

function createEnvelope(
  request: ProviderStartRequest,
  eventType: RuntimeEventType,
  payload: Record<string, unknown>,
  sequence: number,
  uuid: () => string,
  now: () => string,
): RuntimeEventEnvelope {
  return {
    event_id: uuid(),
    session_id: request.session_id,
    turn_id: request.turn_id,
    sequence,
    event_type: eventType,
    timestamp: now(),
    payload,
    idempotency_key: `${request.idempotency_key}:event:${sequence}`,
  };
}

function buildPrompt(request: ProviderStartRequest): unknown {
  if (request.input.every(block => block.type === "text")) {
    return request.input.map(block => block.type === "text" ? block.text : "").join("\n");
  }
  const nativeSessionId = request.native_session_id ?? "";
  return (async function* () {
    yield {
      type: "user",
      parent_tool_use_id: null,
      session_id: nativeSessionId,
      message: {
        role: "user",
        content: request.input.map(block => block.type === "text"
          ? { type: "text", text: block.text }
          : {
              type: "image",
              source: { type: "base64", media_type: block.media_type, data: block.data },
            }),
      },
    };
  })();
}

async function loadDefaultSdk(): Promise<ClaudeSdkAdapter> {
  // A variable module specifier keeps this adapter type-safe without compiling
  // the large vendored Obsidian dependency graph. package.json pins 0.3.226.
  const moduleName = "@anthropic-ai/claude-agent-sdk";
  const sdk = await import(moduleName) as unknown as ClaudeSdkAdapter;
  if (typeof sdk.query !== "function" || typeof sdk.forkSession !== "function") {
    throw new TypeError("Claude Agent SDK does not expose query/forkSession");
  }
  return sdk;
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
