/** Mirrored from @textbook-agent/agent-protocol's JSON event contract. */
export const AGENT_EVENT_TYPES = [
  "turn_started",
  "user_message",
  "model_text_delta",
  "thinking_delta",
  "tool_started",
  "tool_progress",
  "tool_completed",
  "tool_failed",
  "subagent_started",
  "subagent_completed",
  "usage",
  "compaction",
  "session_state",
  "index_state",
  "error",
] as const;

export type AgentEventType = (typeof AGENT_EVENT_TYPES)[number];

export interface AgentEventEnvelope {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  sequence: number;
  event_type: AgentEventType;
  timestamp: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
}

export function parseAgentEvent(value: unknown): AgentEventEnvelope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("event must be an object");
  }
  const event = value as Record<string, unknown>;
  if (!Number.isSafeInteger(event.sequence) || Number(event.sequence) < 1) {
    throw new TypeError("event.sequence must be a positive safe integer");
  }
  for (const key of ["event_id", "session_id", "event_type", "timestamp", "idempotency_key"] as const) {
    const field = event[key];
    if (typeof field !== "string" || field.length === 0) {
      throw new TypeError(`event.${key} is required`);
    }
  }
  if (event.turn_id !== null && typeof event.turn_id !== "string") {
    throw new TypeError("event.turn_id must be a string or null");
  }
  if (
    typeof event.event_type !== "string"
    || !AGENT_EVENT_TYPES.includes(event.event_type as AgentEventType)
  ) {
    throw new TypeError("event.event_type is invalid");
  }
  if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) {
    throw new TypeError("event.payload must be an object");
  }
  return event as unknown as AgentEventEnvelope;
}

export type AgentSessionState =
  | "running"
  | "waiting_input"
  | "stopped"
  | "failed"
  | "archived";

export interface AgentSidecarReference {
  id: string;
  sha256: string;
  size: number;
  mediaType: string;
  uri?: string;
  previewBytes?: number;
  includedInContext?: boolean;
}

export interface AgentMessageBlock {
  id: string;
  eventId: string;
  turnId: string | null;
  role: "user" | "assistant";
  text: string;
  streaming: boolean;
  sidecar?: AgentSidecarReference;
}

export interface AgentThinkingBlock {
  id: string;
  eventId: string;
  turnId: string | null;
  text: string;
  streaming: boolean;
  sidecar?: AgentSidecarReference;
}

export type AgentToolState = "running" | "completed" | "failed";

export interface AgentToolView {
  id: string;
  turnId: string | null;
  name: string;
  kind: string;
  state: AgentToolState;
  input?: unknown;
  progress?: string;
  output?: unknown;
  error?: string;
  startedAt?: string;
  completedAt?: string;
  sidecar?: AgentSidecarReference;
  payload: Record<string, unknown>;
}

export interface AgentSubagentView {
  id: string;
  turnId: string | null;
  name: string;
  state: "running" | "completed";
  result?: unknown;
  startedAt?: string;
  completedAt?: string;
  payload: Record<string, unknown>;
}

export interface AgentErrorView {
  code?: string;
  message: string;
  [key: string]: unknown;
}

export interface AgentView {
  events: AgentEventEnvelope[];
  lastSequence: number;
  needsReplay: boolean;
  messages: AgentMessageBlock[];
  thinking: AgentThinkingBlock[];
  tools: Record<string, AgentToolView>;
  subagents: Record<string, AgentSubagentView>;
  usage: Record<string, unknown>;
  sessionState: AgentSessionState | null;
  indexState: Record<string, unknown> | null;
  error: AgentErrorView | null;
  compactions: Record<string, unknown>[];
  sidecars: Record<string, AgentSidecarReference>;
}

export function emptyAgentView(): AgentView {
  return {
    events: [],
    lastSequence: 0,
    needsReplay: false,
    messages: [],
    thinking: [],
    tools: {},
    subagents: {},
    usage: {},
    sessionState: null,
    indexState: null,
    error: null,
    compactions: [],
    sidecars: {},
  };
}

function deepEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (typeof left !== "object" || left === null || typeof right !== "object" || right === null) {
    return false;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false;
    return left.every((value, index) => deepEqual(value, right[index]));
  }

  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord).sort();
  const rightKeys = Object.keys(rightRecord).sort();
  return (
    leftKeys.length === rightKeys.length
    && leftKeys.every(
      (key, index) => key === rightKeys[index] && deepEqual(leftRecord[key], rightRecord[key]),
    )
  );
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function sidecarFrom(payload: Record<string, unknown>): AgentSidecarReference | undefined {
  const id = asString(payload.sidecar_id);
  const sha256 = asString(payload.sha256);
  const mediaType = asString(payload.media_type);
  const size = payload.size;
  if (!id || !sha256 || !mediaType || typeof size !== "number" || !Number.isFinite(size)) {
    return undefined;
  }
  return {
    id,
    sha256,
    size,
    mediaType,
    ...(asString(payload.sidecar_uri) ? { uri: asString(payload.sidecar_uri) } : {}),
    ...(typeof payload.preview_bytes === "number" ? { previewBytes: payload.preview_bytes } : {}),
    ...(typeof payload.included_in_context === "boolean"
      ? { includedInContext: payload.included_in_context }
      : {}),
  };
}

const KNOWLEDGE_CONTEXT_MARKER = "以下内容来自用户有权访问的知识库，仅作为参考：";

function visibleUserMessage(payload: Record<string, unknown>): string {
  const text = asString(payload.display_text)
    ?? asString(payload.prompt)
    ?? asString(payload.text)
    ?? asString(payload.message)
    ?? "";
  const contextMarker = text.indexOf(KNOWLEDGE_CONTEXT_MARKER);
  return contextMarker < 0 ? text : text.slice(0, contextMarker).trimEnd();
}

function appendMessageDelta(
  messages: AgentMessageBlock[],
  event: AgentEventEnvelope,
  role: AgentMessageBlock["role"],
  streaming: boolean,
): AgentMessageBlock[] {
  const text = role === "user"
    ? visibleUserMessage(event.payload)
    : asString(event.payload.text) ?? "";
  const sidecar = sidecarFrom(event.payload);
  const last = messages.at(-1);
  if (role === "assistant" && last?.role === role && last.turnId === event.turn_id) {
    return [
      ...messages.slice(0, -1),
      {
        ...last,
        text: `${last.text}${text}`,
        streaming,
        ...(sidecar ? { sidecar } : {}),
      },
    ];
  }
  return [
    ...messages,
    {
      id: `${role}-${event.turn_id ?? event.event_id}`,
      eventId: event.event_id,
      turnId: event.turn_id,
      role,
      text,
      streaming,
      ...(sidecar ? { sidecar } : {}),
    },
  ];
}

function appendThinkingDelta(
  thinking: AgentThinkingBlock[],
  event: AgentEventEnvelope,
): AgentThinkingBlock[] {
  const text = asString(event.payload.text) ?? "";
  const sidecar = sidecarFrom(event.payload);
  const last = thinking.at(-1);
  if (last?.turnId === event.turn_id) {
    return [
      ...thinking.slice(0, -1),
      {
        ...last,
        text: `${last.text}${text}`,
        ...(sidecar ? { sidecar } : {}),
      },
    ];
  }
  return [
    ...thinking,
    {
      id: `thinking-${event.turn_id ?? event.event_id}`,
      eventId: event.event_id,
      turnId: event.turn_id,
      text,
      streaming: true,
      ...(sidecar ? { sidecar } : {}),
    },
  ];
}

function toolId(event: AgentEventEnvelope): string {
  return asString(event.payload.tool_call_id) ?? event.event_id;
}

function subagentId(event: AgentEventEnvelope): string {
  return asString(event.payload.subagent_id) ?? event.event_id;
}

function projectEvent(state: AgentView, event: AgentEventEnvelope): AgentView {
  const payload = event.payload;
  const sidecar = sidecarFrom(payload);
  let next = sidecar
    ? { ...state, sidecars: { ...state.sidecars, [sidecar.id]: sidecar } }
    : state;

  switch (event.event_type) {
    case "user_message":
      return { ...next, messages: appendMessageDelta(next.messages, event, "user", false) };
    case "model_text_delta":
      return { ...next, messages: appendMessageDelta(next.messages, event, "assistant", true) };
    case "thinking_delta":
      return { ...next, thinking: appendThinkingDelta(next.thinking, event) };
    case "tool_started": {
      const id = toolId(event);
      const name = asString(payload.name) ?? asString(payload.tool_name) ?? "Tool";
      next = {
        ...next,
        tools: {
          ...next.tools,
          [id]: {
            id,
            turnId: event.turn_id,
            name,
            kind: asString(payload.tool_kind) ?? asString(payload.kind) ?? name.toLowerCase(),
            state: "running",
            input: payload.input,
            startedAt: asString(payload.started_at) ?? event.timestamp,
            ...(sidecar ? { sidecar } : {}),
            payload: { ...payload },
          },
        },
      };
      return next;
    }
    case "tool_progress":
    case "tool_completed":
    case "tool_failed": {
      const id = toolId(event);
      const previous = next.tools[id] ?? {
        id,
        turnId: event.turn_id,
        name: asString(payload.name) ?? "Tool",
        kind: asString(payload.tool_kind) ?? "tool",
        state: "running" as const,
        payload: {},
      };
      const stateValue: AgentToolState = event.event_type === "tool_completed"
        ? "completed"
        : event.event_type === "tool_failed"
          ? "failed"
          : "running";
      return {
        ...next,
        tools: {
          ...next.tools,
          [id]: {
            ...previous,
            state: stateValue,
            progress: asString(payload.text) ?? asString(payload.progress) ?? previous.progress,
            output: payload.output ?? previous.output,
            error: asString(payload.error) ?? asString(payload.message) ?? previous.error,
            completedAt: stateValue === "running"
              ? previous.completedAt
              : asString(payload.completed_at) ?? event.timestamp,
            ...(sidecar ? { sidecar } : {}),
            payload: { ...previous.payload, ...payload },
          },
        },
      };
    }
    case "subagent_started": {
      const id = subagentId(event);
      return {
        ...next,
        subagents: {
          ...next.subagents,
          [id]: {
            id,
            turnId: event.turn_id,
            name: asString(payload.name) ?? "Subagent",
            state: "running",
            startedAt: asString(payload.started_at) ?? event.timestamp,
            payload: { ...payload },
          },
        },
      };
    }
    case "subagent_completed": {
      const id = subagentId(event);
      const previous = next.subagents[id] ?? {
        id,
        turnId: event.turn_id,
        name: asString(payload.name) ?? "Subagent",
        state: "running" as const,
        payload: {},
      };
      return {
        ...next,
        subagents: {
          ...next.subagents,
          [id]: {
            ...previous,
            state: "completed",
            result: payload.result,
            completedAt: asString(payload.completed_at) ?? event.timestamp,
            payload: { ...previous.payload, ...payload },
          },
        },
      };
    }
    case "usage":
      return { ...next, usage: { ...next.usage, ...payload } };
    case "compaction":
      return { ...next, compactions: [...next.compactions, { ...payload }] };
    case "session_state": {
      const runtimeState = asString(payload.state);
      const sessionState = runtimeState === "completed" ? "waiting_input" : runtimeState;
      if (
        sessionState !== "running"
        && sessionState !== "waiting_input"
        && sessionState !== "stopped"
        && sessionState !== "failed"
        && sessionState !== "archived"
      ) return next;
      if (sessionState === "running") return { ...next, sessionState };
      return {
        ...next,
        sessionState,
        messages: next.messages.map((message) =>
          message.role === "assistant" && message.streaming
            ? { ...message, streaming: false }
            : message),
        thinking: next.thinking.map((block) =>
          block.streaming ? { ...block, streaming: false } : block),
      };
    }
    case "index_state":
      return { ...next, indexState: { ...payload } };
    case "error":
      return {
        ...next,
        error: {
          ...payload,
          ...(asString(payload.code) ? { code: asString(payload.code) } : {}),
          message: asString(payload.message) ?? "Agent error",
        },
      };
    case "turn_started":
      return { ...next, error: null };
  }
}

export function reduceAgentEvents(
  state: AgentView,
  incoming: AgentEventEnvelope,
): AgentView {
  const existing = state.events.find((item) => item.sequence === incoming.sequence);
  if (existing && deepEqual(existing, incoming)) return state;

  if (incoming.sequence !== state.lastSequence + 1) {
    return { ...state, needsReplay: true };
  }

  return projectEvent(
    {
      ...state,
      events: [...state.events, incoming],
      lastSequence: incoming.sequence,
      needsReplay: false,
    },
    incoming,
  );
}
