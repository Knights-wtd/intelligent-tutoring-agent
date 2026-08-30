export const RUNTIME_EVENT_TYPES = [
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

export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];

export interface RuntimeEventEnvelope {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  sequence: number;
  event_type: RuntimeEventType;
  timestamp: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
}

export function parseRuntimeEvent(value: unknown): RuntimeEventEnvelope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("event must be an object");
  }

  const event = value as Record<string, unknown>;
  if (!Number.isSafeInteger(event.sequence) || Number(event.sequence) < 1) {
    throw new TypeError("event.sequence must be a positive safe integer");
  }

  for (const key of [
    "event_id",
    "session_id",
    "event_type",
    "timestamp",
    "idempotency_key",
  ] as const) {
    if (typeof event[key] !== "string" || event[key].length === 0) {
      throw new TypeError(`event.${key} is required`);
    }
  }

  if (event.turn_id !== null && typeof event.turn_id !== "string") {
    throw new TypeError("event.turn_id must be a string or null");
  }
  if (
    typeof event.event_type !== "string"
    || !RUNTIME_EVENT_TYPES.includes(event.event_type as RuntimeEventType)
  ) {
    throw new TypeError("event.event_type is invalid");
  }

  if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) {
    throw new TypeError("event.payload must be an object");
  }

  return event as unknown as RuntimeEventEnvelope;
}
