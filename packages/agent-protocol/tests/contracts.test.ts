import { parseRuntimeEvent } from "../src/events";

describe("runtime event contract", () => {
  it("accepts a monotonic replayable event envelope", () => {
    expect(parseRuntimeEvent({
      event_id: "7d62a87e-b89d-49d7-af1c-7accabc32324",
      session_id: "6bf39da0-d73f-49da-a471-95ca48bb48fa",
      turn_id: "35b7cd1e-2a23-4aa3-a704-9ba1fc4f9265",
      sequence: 1,
      event_type: "model_text_delta",
      timestamp: "2026-08-28T00:00:00Z",
      payload: { text: "hello" },
      idempotency_key: "turn-1-sequence-1",
    }).sequence).toBe(1);
  });

  it("rejects an unknown event type at the protocol boundary", () => {
    expect(() => parseRuntimeEvent({
      event_id: "7d62a87e-b89d-49d7-af1c-7accabc32324",
      session_id: "6bf39da0-d73f-49da-a471-95ca48bb48fa",
      turn_id: null,
      sequence: 2,
      event_type: "silent_truncation",
      timestamp: "2026-08-28T00:00:01Z",
      payload: {},
      idempotency_key: "turn-1-sequence-2",
    })).toThrow("event.event_type is invalid");
  });

  it("rejects a non-string turn identifier", () => {
    expect(() => parseRuntimeEvent({
      event_id: "7d62a87e-b89d-49d7-af1c-7accabc32324",
      session_id: "6bf39da0-d73f-49da-a471-95ca48bb48fa",
      turn_id: 42,
      sequence: 3,
      event_type: "turn_started",
      timestamp: "2026-08-28T00:00:02Z",
      payload: {},
      idempotency_key: "turn-1-sequence-3",
    })).toThrow("event.turn_id must be a string or null");
  });
});
