import { describe, expect, it } from "vitest";

import { parseAgentEvent, reduceAgentEvents, emptyAgentView } from "./agent-events";
import type { AgentEventEnvelope } from "./agent-events";

function event(overrides: Partial<AgentEventEnvelope> = {}): AgentEventEnvelope {
  return {
    event_id: "event-1",
    session_id: "session",
    turn_id: "turn-1",
    sequence: 1,
    event_type: "model_text_delta",
    timestamp: "2026-08-28T00:00:00Z",
    payload: { text: "hello" },
    idempotency_key: "one",
    ...overrides,
  };
}

function apply(events: AgentEventEnvelope[]) {
  return events.reduce(reduceAgentEvents, emptyAgentView());
}

describe("agent event contract", () => {
  it("accepts the shared protocol envelope and rejects unknown event types", () => {
    expect(parseAgentEvent(event())).toEqual(event());
    expect(() => parseAgentEvent({ ...event(), event_type: "unknown" })).toThrow(
      "event.event_type is invalid",
    );
  });
});
describe("agent event reducer", () => {
  it("deduplicates replayed events and preserves sequence order", () => {
    const once = reduceAgentEvents(emptyAgentView(), event());
    const replayed = reduceAgentEvents(
      once,
      event({ sequence: 1, idempotency_key: "one" }),
    );

    expect(replayed.events).toHaveLength(1);
    expect(replayed.lastSequence).toBe(1);
  });

  it("deduplicates a structurally identical replay even when payload key order differs", () => {
    const original = event({ payload: { text: "hello", metadata: { a: 1, b: 2 } } });
    const replay = event({ payload: { metadata: { b: 2, a: 1 }, text: "hello" } });

    const state = reduceAgentEvents(reduceAgentEvents(emptyAgentView(), original), replay);

    expect(state.events).toHaveLength(1);
    expect(state.needsReplay).toBe(false);
  });

  it("flags a sequence gap without accepting or inventing missing content", () => {
    const once = reduceAgentEvents(emptyAgentView(), event());
    const gap = reduceAgentEvents(
      once,
      event({ event_id: "event-3", sequence: 3, idempotency_key: "three" }),
    );

    expect(gap.events.map((item) => item.sequence)).toEqual([1]);
    expect(gap.lastSequence).toBe(1);
    expect(gap.needsReplay).toBe(true);
  });

  it("projects messages, thinking, tools, subagents, usage, state, index, errors and sidecars", () => {
    const state = apply([
      event({ event_id: "1", sequence: 1, event_type: "user_message", payload: { text: "question" }, idempotency_key: "1" }),
      event({ event_id: "2", sequence: 2, event_type: "model_text_delta", payload: { text: "answer " }, idempotency_key: "2" }),
      event({ event_id: "3", sequence: 3, event_type: "model_text_delta", payload: { text: "continues" }, idempotency_key: "3" }),
      event({ event_id: "4", sequence: 4, event_type: "thinking_delta", payload: { text: "reasoning" }, idempotency_key: "4" }),
      event({ event_id: "5", sequence: 5, event_type: "tool_started", payload: { tool_call_id: "tool-1", tool_kind: "bash", name: "Bash", input: { command: "pwd" } }, idempotency_key: "5" }),
      event({ event_id: "6", sequence: 6, event_type: "tool_progress", payload: { tool_call_id: "tool-1", text: "running" }, idempotency_key: "6" }),
      event({
        event_id: "7",
        sequence: 7,
        event_type: "tool_completed",
        payload: {
          tool_call_id: "tool-1",
          output: "large output is external",
          sidecar_id: "sidecar-1",
          sha256: "abc",
          size: 123456,
          media_type: "text/plain",
        },
        idempotency_key: "7",
      }),
      event({ event_id: "8", sequence: 8, event_type: "subagent_started", payload: { subagent_id: "sub-1", name: "researcher" }, idempotency_key: "8" }),
      event({ event_id: "9", sequence: 9, event_type: "subagent_completed", payload: { subagent_id: "sub-1", result: "done" }, idempotency_key: "9" }),
      event({ event_id: "10", sequence: 10, event_type: "usage", payload: { input_tokens: 10, output_tokens: 20 }, idempotency_key: "10" }),
      event({ event_id: "11", sequence: 11, event_type: "session_state", payload: { state: "waiting_input" }, idempotency_key: "11" }),
      event({ event_id: "12", sequence: 12, event_type: "index_state", payload: { state: "indexing", change_set_id: "change-1" }, idempotency_key: "12" }),
      event({ event_id: "13", sequence: 13, event_type: "error", payload: { code: "provider_error", message: "provider failed" }, idempotency_key: "13" }),
    ]);

    expect(state.messages.map(({ role, text }) => ({ role, text }))).toEqual([
      { role: "user", text: "question" },
      { role: "assistant", text: "answer continues" },
    ]);
    expect(state.thinking).toEqual([
      expect.objectContaining({ turnId: "turn-1", text: "reasoning" }),
    ]);
    expect(state.tools["tool-1"]).toEqual(
      expect.objectContaining({ state: "completed", kind: "bash", progress: "running" }),
    );
    expect(state.tools["tool-1"].sidecar).toEqual(
      expect.objectContaining({ id: "sidecar-1", size: 123456, mediaType: "text/plain" }),
    );
    expect(state.subagents["sub-1"]).toEqual(
      expect.objectContaining({ state: "completed", name: "researcher", result: "done" }),
    );
    expect(state.usage).toEqual({ input_tokens: 10, output_tokens: 20 });
    expect(state.sessionState).toBe("waiting_input");
    expect(state.indexState).toEqual({ state: "indexing", change_set_id: "change-1" });
    expect(state.error).toEqual({ code: "provider_error", message: "provider failed" });
    expect(state.sidecars["sidecar-1"]).toEqual(
      expect.objectContaining({ sha256: "abc", size: 123456 }),
    );
  });

  it("does not mark completed message blocks as streaming when a later turn resumes", () => {
    const state = apply([
      event({ event_id: "1", sequence: 1, turn_id: "turn-1", event_type: "model_text_delta", payload: { text: "done" }, idempotency_key: "1" }),
      event({ event_id: "2", sequence: 2, turn_id: "turn-1", event_type: "session_state", payload: { state: "waiting_input" }, idempotency_key: "2" }),
      event({ event_id: "3", sequence: 3, turn_id: "turn-2", event_type: "session_state", payload: { state: "running" }, idempotency_key: "3" }),
    ]);

    expect(state.messages[0]).toEqual(expect.objectContaining({ turnId: "turn-1", streaming: false }));
  });

  it("maps runtime completed sessions to waiting input while preserving failed state", () => {
    const completed = apply([
      event({ event_id: "1", sequence: 1, event_type: "session_state", payload: { state: "running" }, idempotency_key: "1" }),
      event({ event_id: "2", sequence: 2, event_type: "model_text_delta", payload: { text: "done" }, idempotency_key: "2" }),
      event({ event_id: "3", sequence: 3, event_type: "session_state", payload: { state: "completed" }, idempotency_key: "3" }),
    ]);
    const failed = apply([
      event({ event_id: "1", sequence: 1, event_type: "session_state", payload: { state: "failed" }, idempotency_key: "1" }),
    ]);

    expect(completed.sessionState).toBe("waiting_input");
    expect(completed.messages[0]).toEqual(expect.objectContaining({ streaming: false }));
    expect(failed.sessionState).toBe("failed");
  });

  it("marks failed tools and keeps compaction records", () => {
    const state = apply([
      event({ event_id: "1", sequence: 1, event_type: "tool_started", payload: { tool_call_id: "tool-1", name: "WebFetch" }, idempotency_key: "1" }),
      event({ event_id: "2", sequence: 2, event_type: "tool_failed", payload: { tool_call_id: "tool-1", error: "blocked" }, idempotency_key: "2" }),
      event({ event_id: "3", sequence: 3, event_type: "compaction", payload: { before_tokens: 900000, after_tokens: 100000 }, idempotency_key: "3" }),
    ]);

    expect(state.tools["tool-1"]).toEqual(
      expect.objectContaining({ state: "failed", error: "blocked" }),
    );
    expect(state.compactions).toEqual([{ before_tokens: 900000, after_tokens: 100000 }]);
  });
});
