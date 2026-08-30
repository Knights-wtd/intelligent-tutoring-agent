import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import type { RuntimeEventEnvelope } from "@textbook-agent/agent-protocol";

import { loadRuntimeConfig } from "../src/config";
import { FaroProvider } from "../src/providers/faro/FaroProvider";
import type { ProviderStartRequest } from "../src/providers/types";

const TEST_MODEL = "gemini-3.7-flash-tiered";

function makeRequest(overrides: Partial<ProviderStartRequest> = {}): ProviderStartRequest {
  return {
    session_id: "app-session",
    turn_id: "turn-1",
    input: [{ type: "text", text: "你好" }],
    workspace_roots: ["C:/vault"],
    provider: "faro",
    model: TEST_MODEL,
    permission_mode: "bypassPermissions",
    capability: "signed-capability",
    callback_url: "http://127.0.0.1/events",
    idempotency_key: "start-1",
    ...overrides,
  };
}

async function collect(
  provider: FaroProvider,
  request = makeRequest(),
  signal = new AbortController().signal,
): Promise<RuntimeEventEnvelope[]> {
  const events: RuntimeEventEnvelope[] = [];
  for await (const event of provider.start(request, signal)) events.push(event);
  return events;
}

function successResponse(text = "回答"): Response {
  return Response.json({ choices: [{ message: { content: text } }] });
}

function mockFetch(
  implementation: (input: string | URL | Request, init?: RequestInit) => Promise<Response>,
) {
  const mock = jest.fn(implementation);
  return { mock, fetch: mock as unknown as typeof fetch };
}

async function listen(server: Server): Promise<{ origin: string; close: () => Promise<void> }> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve());
    }),
  };
}

describe("FaroProvider", () => {
  it("sends the OpenAI-compatible request and emits the successful event sequence", async () => {
    const { mock, fetch } = mockFetch(async () => successResponse("这是回答"));
    let nextId = 0;
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1/",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
      uuid: () => `id-${++nextId}`,
      now: () => "2026-08-30T00:00:00.000Z",
    });

    const events = await collect(provider);

    expect(mock).toHaveBeenCalledTimes(1);
    const [url, init] = mock.mock.calls[0]!;
    expect(url).toBe("https://faro.example/v1/chat/completions");
    expect(new Headers(init?.headers).get("authorization")).toBe("Bearer test-api-key");
    expect(new Headers(init?.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({
      model: TEST_MODEL,
      messages: [
        expect.objectContaining({ role: "system" }),
        { role: "user", content: "你好" },
      ],
    });
    expect(events.map(event => event.event_type)).toEqual([
      "turn_started",
      "user_message",
      "model_text_delta",
      "session_state",
    ]);
    expect(events[1]?.payload).toMatchObject({ text: "你好" });
    expect(events[1]?.payload).not.toHaveProperty("message");
    expect(events[0]?.payload).toMatchObject({
      native_session_id: "faro-id-1",
      provider: "faro",
      model: TEST_MODEL,
    });
    expect(events[2]?.payload).toMatchObject({ text: "这是回答" });
    expect(events[3]?.payload).toMatchObject({ state: "completed" });
    expect(events.every(event => event.payload.native_session_id === "faro-id-1")).toBe(true);
  });

  it("keeps injected knowledge context out of the visible user message", async () => {
    const { mock, fetch } = mockFetch(async () => successResponse("基于知识库的回答"));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
      uuid: () => "fixed-id",
    });

    const events = await collect(provider, makeRequest({
      input: [
        { type: "text", text: "用户原始提问" },
        { type: "text", text: "以下内容来自用户有权访问的知识库，仅作为参考：隐藏检索片段" },
      ],
    }));

    expect(events.find(event => event.event_type === "user_message")?.payload).toMatchObject({
      text: "用户原始提问",
    });
    const body = JSON.parse(String(mock.mock.calls[0]?.[1]?.body)) as {
      messages: Array<{ role: string; content: string }>;
    };
    expect(body.messages.at(-1)?.content).toContain("用户原始提问");
    expect(body.messages.at(-1)?.content).toContain("隐藏检索片段");
  });
  it("keeps multi-turn history by native id, copies it on fork, and clears it on rewind", async () => {
    const bodies: Array<{ messages: Array<{ role: string; content: string }> }> = [];
    const answers = ["第一答", "第二答", "分支答", "重置答"];
    const { fetch } = mockFetch(async (_input, init) => {
      bodies.push(JSON.parse(String(init?.body)) as { messages: Array<{ role: string; content: string }> });
      return successResponse(answers[bodies.length - 1]);
    });
    let nextId = 0;
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
      uuid: () => `uuid-${++nextId}`,
    });

    const first = await collect(provider);
    const nativeSessionId = String(first[0]?.payload.native_session_id);
    await collect(provider, makeRequest({
      turn_id: "turn-2",
      input: [{ type: "text", text: "第二问" }],
      idempotency_key: "start-2",
    }));

    expect(bodies[1]?.messages).toEqual([
      expect.objectContaining({ role: "system" }),
      { role: "user", content: "你好" },
      { role: "assistant", content: "第一答" },
      { role: "user", content: "第二问" },
    ]);

    const fork = await provider.fork("app-session", "checkpoint-ignored");
    expect(fork.native_session_id).not.toBe(nativeSessionId);
    await collect(provider, makeRequest({
      session_id: "fork-session",
      native_session_id: fork.native_session_id,
      turn_id: "fork-turn",
      input: [{ type: "text", text: "分支问题" }],
      idempotency_key: "fork-start",
    }));
    expect(bodies[2]?.messages).toEqual([
      expect.objectContaining({ role: "system" }),
      { role: "user", content: "你好" },
      { role: "assistant", content: "第一答" },
      { role: "user", content: "第二问" },
      { role: "assistant", content: "第二答" },
      { role: "user", content: "分支问题" },
    ]);

    await provider.rewind("app-session", "checkpoint-ignored");
    await collect(provider, makeRequest({
      turn_id: "turn-3",
      input: [{ type: "text", text: "重置后" }],
      idempotency_key: "start-3",
    }));
    expect(bodies[3]?.messages).toEqual([
      expect.objectContaining({ role: "system" }),
      { role: "user", content: "重置后" },
    ]);
  });

  it("routes HTTP requests through FARO_PROXY_URL without using direct fetch", async () => {
    let requestUrl = "";
    let authorization = "";
    let requestBody = "";
    const proxy = createServer((request, response) => {
      requestUrl = request.url ?? "";
      authorization = String(request.headers.authorization ?? "");
      request.on("data", chunk => { requestBody += chunk.toString(); });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ choices: [{ message: { content: "代理回答" } }] }));
      });
    });
    const runtime = await listen(proxy);
    const direct = mockFetch(async () => { throw new Error("direct fetch must not run"); });
    try {
      const provider = new FaroProvider({
        apiBaseUrl: "http://faro.invalid/v1",
        apiKey: "test-api-key",
        proxyUrl: runtime.origin,
        model: TEST_MODEL,
        fetchImpl: direct.fetch,
      });
      const events = await collect(provider);
      expect(events[2]?.payload).toMatchObject({ text: "代理回答" });
      expect(direct.mock).not.toHaveBeenCalled();
      expect(requestUrl).toBe("http://faro.invalid/v1/chat/completions");
      expect(authorization).toBe("Bearer test-api-key");
      expect(JSON.parse(requestBody)).toMatchObject({ model: TEST_MODEL });
    } finally {
      await runtime.close();
    }
  });

  it("uses HTTPS CONNECT and only falls back before the Faro POST is sent", async () => {
    let connectTarget = "";
    const proxy = createServer();
    proxy.on("connect", (request, socket) => {
      connectTarget = request.url ?? "";
      socket.end("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n");
    });
    const runtime = await listen(proxy);
    const direct = mockFetch(async () => successResponse("直连回退"));
    try {
      const provider = new FaroProvider({
        apiBaseUrl: "https://faro.example/v1",
        apiKey: "test-api-key",
        proxyUrl: runtime.origin,
        model: TEST_MODEL,
        fetchImpl: direct.fetch,
      });
      const events = await collect(provider);
      expect(connectTarget).toBe("faro.example:443");
      expect(direct.mock).toHaveBeenCalledTimes(1);
      expect(events[2]?.payload).toMatchObject({ text: "直连回退" });
    } finally {
      await runtime.close();
    }
  });

  it("loads the Runtime-specific proxy first, then the shared Faro proxy", () => {
    const required = {
      AGENT_RUNTIME_TOKEN: "runtime-test-token",
      AGENT_RUNTIME_SIDECAR_ROOT: "C:/tmp/sidecars",
    };
    expect(loadRuntimeConfig({
      ...required,
      FARO_PROXY_URL: "http://shared-proxy.invalid:8080",
    }, "24.18.0").faroProxyUrl).toBe("http://shared-proxy.invalid:8080");
    expect(loadRuntimeConfig({
      ...required,
      FARO_PROXY_URL: "http://shared-proxy.invalid:8080",
      AGENT_RUNTIME_FARO_PROXY_URL: "http://runtime-proxy.invalid:8081",
    }, "24.18.0").faroProxyUrl).toBe("http://runtime-proxy.invalid:8081");
    expect(() => loadRuntimeConfig({
      ...required,
      FARO_PROXY_URL: "https://not-an-http-proxy.invalid",
    }, "24.18.0")).toThrow("AGENT_RUNTIME_FARO_PROXY_URL must be an absolute http:// proxy URL");
  });

  it.each([
    [401, "faro_unauthorized"],
    [429, "faro_rate_limited"],
    [500, "faro_request_rejected"],
  ])("maps HTTP %i to %s", async (status, code) => {
    const { fetch } = mockFetch(async () => new Response("{}", { status }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });
    await expect(collect(provider)).rejects.toMatchObject({ code });
  });

  it("rejects invalid JSON", async () => {
    const { fetch } = mockFetch(async () => new Response("{not-json", {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });
    await expect(collect(provider)).rejects.toMatchObject({ code: "faro_response_invalid" });
  });

  it("rejects an empty assistant response", async () => {
    const { mock, fetch } = mockFetch(async () => Response.json({
      choices: [{ finish_reason: "stop", message: { content: "   " } }],
      usage: { prompt_tokens: 12, completion_tokens: 0, total_tokens: 12 },
    }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });
    await expect(collect(provider)).rejects.toMatchObject({
      code: "faro_response_empty",
      retryable: false,
      safeMetadata: {
        choices_count: 1,
        finish_reason: "stop",
        content_type: "string",
        content_text_length: 3,
        reasoning_content_length: 0,
        tool_calls_count: 0,
        usage: { prompt_tokens: 12, completion_tokens: 0, total_tokens: 12 },
      },
    });
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("joins common content text parts as the final answer", async () => {
    const { fetch } = mockFetch(async () => Response.json({
      choices: [{
        finish_reason: "stop",
        message: {
          content: [
            { type: "text", text: "第一段" },
            { type: "output_text", text: { value: "第二段" } },
          ],
        },
      }],
    }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });

    const events = await collect(provider);

    expect(events[2]?.payload).toMatchObject({ text: "第一段第二段" });
  });

  it("diagnoses reasoning-only responses without exposing reasoning or retrying", async () => {
    const privateReasoning = "private-reasoning-must-not-leak";
    const { mock, fetch } = mockFetch(async () => Response.json({
      id: "response-id",
      choices: [{
        finish_reason: "stop",
        message: { content: null, reasoning_content: privateReasoning },
      }],
    }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });

    let failure: unknown;
    try {
      await collect(provider);
    } catch (error) {
      failure = error;
    }

    expect(failure).toMatchObject({
      code: "faro_response_reasoning_only",
      retryable: false,
      safeMetadata: {
        top_level_keys: ["choices", "id"],
        choices_count: 1,
        finish_reason: "stop",
        message_keys: ["content", "reasoning_content"],
        content_type: "null",
        content_text_length: 0,
        reasoning_content_length: privateReasoning.length,
        tool_calls_count: 0,
      },
    });
    expect(JSON.stringify(failure)).not.toContain(privateReasoning);
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("uses a stable blocked-response code with safe metadata", async () => {
    const refusal = "private-refusal-must-not-leak";
    const { fetch } = mockFetch(async () => Response.json({
      choices: [{
        finish_reason: "content_filter",
        message: { content: null, refusal },
      }],
      promptFeedback: { blockReason: "SAFETY" },
    }));
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });

    let failure: unknown;
    try {
      await collect(provider);
    } catch (error) {
      failure = error;
    }

    expect(failure).toMatchObject({
      code: "faro_response_blocked",
      retryable: false,
      safeMetadata: {
        finish_reason: "content_filter",
        refusal_length: refusal.length,
        prompt_feedback_keys: ["blockReason"],
        block_reason: "SAFETY",
      },
    });
    expect(JSON.stringify(failure)).not.toContain(refusal);
  });

  it("aborts the in-flight Faro request", async () => {
    let requestStarted!: () => void;
    const started = new Promise<void>(resolve => { requestStarted = resolve; });
    const { fetch } = mockFetch(async (_input, init) => {
      requestStarted();
      return new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        const abort = () => reject(signal?.reason ?? new Error("aborted"));
        if (signal?.aborted) abort();
        else signal?.addEventListener("abort", abort, { once: true });
      });
    });
    const provider = new FaroProvider({
      apiBaseUrl: "https://faro.example/v1",
      apiKey: "test-api-key",
      model: TEST_MODEL,
      fetchImpl: fetch,
    });
    const controller = new AbortController();
    const consuming = collect(provider, makeRequest(), controller.signal);
    await started;
    controller.abort(new Error("cancelled by test"));
    await expect(consuming).rejects.toMatchObject({ code: "faro_aborted" });
  });
});
