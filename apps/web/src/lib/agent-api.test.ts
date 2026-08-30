import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AgentApiError,
  agentApi,
  agentWebSocketUrl,
  connectAgentEvents,
} from "./agent-api";
import type { AgentConnectionState, AgentEventEnvelope } from "./agent-api";

function event(sequence: number): AgentEventEnvelope {
  return {
    event_id: `event-${sequence}`,
    session_id: "session",
    turn_id: "turn-1",
    sequence,
    event_type: "model_text_delta",
    timestamp: "2026-08-28T00:00:00Z",
    payload: { text: `chunk-${sequence}` },
    idempotency_key: `key-${sequence}`,
  };
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeWebSocket.instances.push(this);
  }

  close(code = 1000): void {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  message(value: unknown): void {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }

  disconnect(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

describe("agent API client", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("builds direct FastAPI websocket URLs for HTTP and HTTPS origins", () => {
    expect(agentWebSocketUrl("session", 9, "http://localhost:8000")).toBe(
      "ws://localhost:8000/api/v1/agent/ws/session?after=9",
    );
    expect(agentWebSocketUrl("session/with slash", 10, "https://api.example.test")).toBe(
      "wss://api.example.test/api/v1/agent/ws/session%2Fwith%20slash?after=10",
    );
  });

  it("normalizes the API router's bare event array into the Web replay contract", async () => {
    const persisted = event(9);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([persisted]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(agentApi.events("session/1", 8)).resolves.toEqual({
      events: [persisted],
      last_sequence: 9,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/agent/sessions/session%2F1/events?after=8",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("keeps a non-zero replay cursor when the bare event array is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));

    await expect(agentApi.events("session-1", 8)).resolves.toEqual({
      events: [],
      last_sequence: 8,
    });
  });

  it("exposes all planned REST controls with cookie credentials and untruncated payloads", async () => {
    const sidecarResponse = new Response("full sidecar", {
      status: 206,
      headers: { "Content-Type": "text/plain" },
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "session" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "session" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "turn" }), { status: 202 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "forked" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ events: [], last_sequence: 8 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ context_window: 1_000_000 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ context_window: 1_000_000 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ runtime: { status: "ok" } }), { status: 200 }))
      .mockResolvedValueOnce(sidecarResponse);
    vi.stubGlobal("fetch", fetchMock);

    const longText = "知识库与网页联合推理。".repeat(100);
    await agentApi.create({ knowledge_base_id: "kb/1", provider: "claude", model: "opus", context_window: 1_000_000 });
    await agentApi.list();
    await agentApi.get("session/1");
    await agentApi.archive("session/1");
    await agentApi.send("session/1", { text: longText, linked_contexts: [{ vault_file_id: "file/1" }] }, "send-key");
    await agentApi.stop("session/1");
    await agentApi.resume("session/1");
    await agentApi.rewind("session/1", { checkpoint_id: "checkpoint-4" });
    await agentApi.fork("session/1", { checkpoint_id: "checkpoint-4" });
    await agentApi.events("session/1", 8);
    await agentApi.settings();
    await agentApi.updateSettings({ context_window: 1_000_000, permission_mode: "bypassPermissions" });
    await agentApi.mcp();
    await agentApi.skills();
    await agentApi.diagnostics();
    await expect(agentApi.sidecar("sidecar/1", { range: "bytes=0-4095" })).resolves.toBe(sidecarResponse);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/agent/sessions",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/v1/agent/sessions/session%2F1/turns",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          prompt: longText,
          linked_contexts: [{ vault_file_id: "file/1" }],
          idempotency_key: "send-key",
        }),
      }),
    );
    expect(new Headers(fetchMock.mock.calls[4][1]?.headers).has("Idempotency-Key")).toBe(false);
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/v1/agent/sessions/session%2F1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      "/api/v1/agent/sessions/session%2F1/rewind",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ checkpoint_id: "checkpoint-4" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      10,
      "/api/v1/agent/sessions/session%2F1/events?after=8",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      16,
      "/api/v1/agent/sidecars/sidecar%2F1",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(new Headers(fetchMock.mock.calls[15][1]?.headers).get("Range")).toBe("bytes=0-4095");
  });

  it("preserves HTTP status and safe server detail on REST failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Runtime unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const error = await agentApi.list().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(AgentApiError);
    expect(error).toEqual(expect.objectContaining({ status: 503, detail: "Runtime unavailable" }));
  });

  it("uses HTTP polling through the same-origin proxy and advances the replay cursor", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([event(10), event(11)]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const received: AgentEventEnvelope[] = [];
    const states: AgentConnectionState[] = [];

    const connection = connectAgentEvents(
      "session",
      9,
      (incoming) => received.push(incoming),
      (state) => states.push(state),
      { pollIntervalMs: 100 },
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(received.map((item) => item.sequence)).toEqual([10, 11]);
    expect(connection.after).toBe(11);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "open", attempt: 0, after: 11 }));
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/agent/sessions/session/events?after=9",
      expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
    );

    await vi.advanceTimersByTimeAsync(100);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/agent/sessions/session/events?after=11",
      expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
    );

    connection.close();
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "closed", after: 11 }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries failed polling requests with exponential backoff and returns to open", async () => {
    vi.useFakeTimers();
    const delayFor = vi.fn((attempt: number) => 100 * 2 ** (attempt - 1));
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockRejectedValueOnce(new Error("still down"))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const states: AgentConnectionState[] = [];

    const connection = connectAgentEvents("session", 4, vi.fn(), (state) => states.push(state), {
      reconnectDelayMs: delayFor,
      pollIntervalMs: 1_000,
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "reconnecting", attempt: 1, after: 4 }));
    await vi.advanceTimersByTimeAsync(99);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "reconnecting", attempt: 2, after: 4 }));
    await vi.advanceTimersByTimeAsync(199);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "open", attempt: 0, after: 4 }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(delayFor.mock.calls.map(([attempt]) => attempt)).toEqual([1, 2]);

    connection.close();
  });

  it.each([401, 403])("stops HTTP polling after unauthorized response %s", async (status) => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const states: AgentConnectionState[] = [];

    connectAgentEvents("session", 0, vi.fn(), (state) => states.push(state));
    await vi.advanceTimersByTimeAsync(0);

    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "unauthorized", code: status }));
    await vi.runAllTimersAsync();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("aborts an active polling request and clears scheduled work on close", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockReturnValue(new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    const states: AgentConnectionState[] = [];

    const connection = connectAgentEvents("session", 0, vi.fn(), (state) => states.push(state));
    const signal = fetchMock.mock.calls[0][1]?.signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    connection.close();

    expect(signal.aborted).toBe(true);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "closed", code: 1000 }));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("advances the cursor on each event and reconnects with exponential backoff", async () => {
    vi.useFakeTimers();
    const received: AgentEventEnvelope[] = [];
    const states: AgentConnectionState[] = [];
    const connection = connectAgentEvents(
      "session",
      9,
      (incoming) => received.push(incoming),
      (state) => states.push(state),
      {
        apiBaseUrl: "http://localhost:8000",
        WebSocketImpl: FakeWebSocket,
        reconnectDelayMs: (attempt) => 100 * 2 ** (attempt - 1),
      },
    );

    expect(FakeWebSocket.instances[0].url).toContain("after=9");
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].message(event(10));
    expect(connection.after).toBe(10);
    expect(received.map((item) => item.sequence)).toEqual([10]);

    FakeWebSocket.instances[0].disconnect();
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "reconnecting", attempt: 1, after: 10 }));
    await vi.advanceTimersByTimeAsync(99);
    expect(FakeWebSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toContain("after=10");

    connection.close();
  });

  it.each([401, 403, 4401, 4403])("stops reconnecting after unauthorized close code %s", async (code) => {
    vi.useFakeTimers();
    const states: AgentConnectionState[] = [];
    connectAgentEvents(
      "session",
      0,
      vi.fn(),
      (state) => states.push(state),
      {
        apiBaseUrl: "https://api.example.test",
        WebSocketImpl: FakeWebSocket,
        reconnectDelayMs: () => 1,
      },
    );

    FakeWebSocket.instances[0].disconnect(code);
    await vi.runAllTimersAsync();

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(states.at(-1)).toEqual(expect.objectContaining({ status: "unauthorized", code }));
  });
});
