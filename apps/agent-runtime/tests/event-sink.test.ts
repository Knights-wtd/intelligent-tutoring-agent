import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { RuntimeEventEnvelope } from "@textbook-agent/agent-protocol";

import { EventSink } from "../src/runtime/EventSink";
import { SidecarStore } from "../src/runtime/SidecarStore";

const event: RuntimeEventEnvelope = {
  event_id: "event-1",
  session_id: "session-1",
  turn_id: "turn-1",
  sequence: 1,
  event_type: "model_text_delta",
  timestamp: "2026-08-28T00:00:00Z",
  payload: { text: "a long answer" },
  idempotency_key: "turn-1-sequence-1",
};

describe("EventSink", () => {
  it("only advances its cursor after a durable ACK and retries duplicate-safe", async () => {
    const attempts: string[] = [];
    const sink = new EventSink({
      callbackUrl: "http://127.0.0.1/events",
      post: async (_url, published) => {
        attempts.push(published.idempotency_key);
        return attempts.length === 1
          ? { ok: false, status: 503, body: {} }
          : { ok: true, status: 200, body: { persisted: true, accepted_sequence: 1 } };
      },
      sleep: async () => {},
    });

    await sink.publish(event);
    expect(attempts).toEqual([event.idempotency_key, event.idempotency_key]);
    expect(sink.cursorFor("session-1")).toBe(1);

    await sink.publish(event);
    expect(attempts).toHaveLength(2);
  });

  it("stores oversized JSON payloads atomically as hashed sidecars without truncation", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-sidecars-"));
    try {
      let published: RuntimeEventEnvelope | undefined;
      const store = new SidecarStore(root);
      const sink = new EventSink({
        callbackUrl: "http://127.0.0.1/events",
        inlineEventBytes: 8,
        sidecarStore: store,
        post: async (_url, envelope) => {
          published = envelope;
          return { ok: true, status: 200, body: { persisted: true, accepted_sequence: 1 } };
        },
      });
      await sink.publish(event);

      expect(published?.payload).toMatchObject({ media_type: "application/json" });
      const sidecarId = String(published?.payload.sidecar_id);
      const bytes = await readFile(store.pathFor(sidecarId), "utf8");
      expect(JSON.parse(bytes)).toEqual(event.payload);
      expect(published?.payload.size).toBe(Buffer.byteLength(bytes));
      expect(published?.payload.sha256).toMatch(/^[a-f0-9]{64}$/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("EventSink callback authentication", () => {
  it("posts callbacks with the configured bearer token", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      JSON.stringify({ persisted: true, accepted_sequence: 1 }),
      { status: 200, headers: { "content-type": "application/json" } },
    ));
    try {
      const sink = new EventSink({
        callbackUrl: "http://127.0.0.1/events",
        callbackToken: "callback-token",
      });

      await sink.publish(event);

      expect(fetchMock).toHaveBeenCalledWith(
        "http://127.0.0.1/events",
        expect.objectContaining({
          headers: expect.objectContaining({ authorization: "Bearer callback-token" }),
        }),
      );
    } finally {
      fetchMock.mockRestore();
    }
  });
});

describe("EventSink delivery robustness", () => {
  it("retries transport exceptions using bounded exponential delays", async () => {
    const waits: number[] = [];
    let attempts = 0;
    const sink = new EventSink({
      callbackUrl: "http://127.0.0.1/events",
      post: async () => {
        attempts += 1;
        if (attempts < 3) throw new Error("network down");
        return { ok: true, status: 200, body: { persisted: true, accepted_sequence: 1 } };
      },
      sleep: async milliseconds => { waits.push(milliseconds); },
    });

    await sink.publish(event);
    expect(attempts).toBe(3);
    expect(waits).toEqual([1_000, 2_000]);
  });

  it("coalesces concurrent publication of the same idempotency key", async () => {
    let attempts = 0;
    const sink = new EventSink({
      callbackUrl: "http://127.0.0.1/events",
      post: async () => {
        attempts += 1;
        await new Promise(resolve => setTimeout(resolve, 5));
        return { ok: true, status: 200, body: { persisted: true, accepted_sequence: 1 } };
      },
    });

    await Promise.all([sink.publish(event), sink.publish(event)]);
    expect(attempts).toBe(1);
  });
});
