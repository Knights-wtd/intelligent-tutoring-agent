import type { AddressInfo } from "node:net";

import type { RuntimeStartRequest, RuntimeStartResponse } from "@textbook-agent/agent-protocol";

import { loadRuntimeConfig } from "../src/config";
import {
  createRuntimeServer,
  type RuntimeControl,
  type RuntimeServerDependencies,
} from "../src/server";

const TOKEN = "runtime-test-token";
const CAPABILITY = "signed-capability";

function startRequest(idempotencyKey = "turn-key-1"): RuntimeStartRequest {
  return {
    session_id: "session-1",
    turn_id: "turn-1",
    input: [{ type: "text", text: "Inspect the complete workspace" }],
    workspace_roots: ["C:/vault/kb-1"],
    provider: "claude",
    model: "claude-sonnet-4-20250514",
    permission_mode: "bypassPermissions",
    capability: CAPABILITY,
    callback_url: "http://127.0.0.1:8000/api/v1/agent/runtime-events",
    idempotency_key: idempotencyKey,
  };
}

async function startServer(overrides: Partial<RuntimeServerDependencies> = {}) {
  const calls = { start: 0, stop: 0, resume: 0, rewind: 0, fork: 0 };
  const response: RuntimeStartResponse = {
    execution_id: "execution-1",
    native_session_id: "native-1",
    accepted_sequence: 9,
  };
  const control: RuntimeControl = {
    async start() { calls.start += 1; return response; },
    async stop() { calls.stop += 1; },
    async resume() { calls.resume += 1; return response; },
    async rewind() { calls.rewind += 1; },
    async fork(_sessionId, _checkpointId, forkSessionId) {
      calls.fork += 1;
      return { session_id: forkSessionId, native_session_id: "native-fork" };
    },
    getSession(sessionId) {
      return sessionId === "session-1"
        ? { session_id: sessionId, provider: "claude", native_session_id: "native-1", sequence: 9 }
        : undefined;
    },
    async diagnostics() { return { status: "ok", active_sessions: 1 }; },
  };
  const config = loadRuntimeConfig({
    AGENT_RUNTIME_HOST: "127.0.0.1",
    AGENT_RUNTIME_PORT: "0",
    AGENT_RUNTIME_TOKEN: TOKEN,
    AGENT_RUNTIME_SIDECAR_ROOT: "C:/tmp/runtime-api-sidecars",
  }, "24.18.0");
  const server = createRuntimeServer(config, { upstreamCommit: "test" }, {
    control,
    verifyCapability(token, sessionId) {
      if (token !== CAPABILITY || sessionId !== "session-1") throw new Error("capability denied");
    },
    async readSidecar(sidecarId, range) {
      expect(sidecarId).toBe("session-1/event-1.json");
      const bytes = Buffer.from("0123456789", "utf8");
      const start = range?.start ?? 0;
      const end = range?.end ?? bytes.length - 1;
      return { bytes: bytes.subarray(start, end + 1), totalSize: bytes.length, mediaType: "application/json" };
    },
    ...overrides,
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, config.host, resolve);
  });
  const { port } = server.address() as AddressInfo;
  return {
    calls,
    origin: `http://${config.host}:${port}`,
    close: () => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())),
  };
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { authorization: `Bearer ${TOKEN}`, "content-type": "application/json", ...extra };
}

describe("runtime control API", () => {
  it("starts once for duplicate idempotency keys and validates capability", async () => {
    const runtime = await startServer();
    try {
      const request = startRequest();
      const first = await fetch(`${runtime.origin}/v1/sessions/start`, {
        method: "POST", headers: headers(), body: JSON.stringify(request),
      });
      const duplicate = await fetch(`${runtime.origin}/v1/sessions/start`, {
        method: "POST", headers: headers(), body: JSON.stringify(request),
      });
      expect(first.status).toBe(202);
      expect(duplicate.status).toBe(202);
      await expect(first.json()).resolves.toMatchObject({ execution_id: "execution-1" });
      await expect(duplicate.json()).resolves.toMatchObject({ execution_id: "execution-1" });
      expect(runtime.calls.start).toBe(1);

      const denied = await fetch(`${runtime.origin}/v1/sessions/start`, {
        method: "POST", headers: headers(), body: JSON.stringify({ ...request, capability: "wrong", idempotency_key: "other" }),
      });
      expect(denied.status).toBe(403);
    } finally { await runtime.close(); }
  });

  it("supports stop, resume, rewind, fork, session lookup and diagnostics", async () => {
    const runtime = await startServer();
    try {
      const mutationHeaders = headers({
        "idempotency-key": "mutation-1",
        "x-workspace-capability": CAPABILITY,
      });
      expect((await fetch(`${runtime.origin}/v1/sessions/session-1/stop`, { method: "POST", headers: mutationHeaders })).status).toBe(204);
      expect((await fetch(`${runtime.origin}/v1/sessions/session-1/resume`, {
        method: "POST", headers: headers(), body: JSON.stringify({ ...startRequest("resume-1"), turn_id: "turn-2" }),
      })).status).toBe(202);
      expect((await fetch(`${runtime.origin}/v1/sessions/session-1/rewind`, {
        method: "POST", headers: headers({ "idempotency-key": "rewind-1", "x-workspace-capability": CAPABILITY }),
        body: JSON.stringify({ checkpoint_id: "checkpoint-1" }),
      })).status).toBe(204);
      const fork = await fetch(`${runtime.origin}/v1/sessions/session-1/fork`, {
        method: "POST", headers: headers({ "idempotency-key": "fork-1", "x-workspace-capability": CAPABILITY }),
        body: JSON.stringify({ checkpoint_id: "checkpoint-1", fork_session_id: "session-fork" }),
      });
      expect(fork.status).toBe(201);
      await expect(fork.json()).resolves.toMatchObject({ session_id: "session-fork" });
      expect((await fetch(`${runtime.origin}/v1/sessions/session-1`, { headers: headers() })).status).toBe(200);
      const diagnostics = await fetch(`${runtime.origin}/v1/diagnostics`, { headers: headers() });
      expect(diagnostics.status).toBe(200);
      await expect(diagnostics.json()).resolves.toMatchObject({ status: "ok" });
      expect(runtime.calls).toEqual({ start: 0, stop: 1, resume: 1, rewind: 1, fork: 1 });
    } finally { await runtime.close(); }
  });

  it("serves sidecars with byte ranges and rejects missing mutation metadata", async () => {
    const runtime = await startServer();
    try {
      const sidecar = await fetch(`${runtime.origin}/v1/sidecars/session-1%2Fevent-1.json`, {
        headers: { authorization: `Bearer ${TOKEN}`, range: "bytes=2-5" },
      });
      expect(sidecar.status).toBe(206);
      expect(sidecar.headers.get("content-range")).toBe("bytes 2-5/10");
      await expect(sidecar.text()).resolves.toBe("2345");

      const missing = await fetch(`${runtime.origin}/v1/sessions/session-1/stop`, {
        method: "POST", headers: headers(),
      });
      expect(missing.status).toBe(400);
      await expect(missing.json()).resolves.toMatchObject({ error: { code: "invalid_request" } });
    } finally { await runtime.close(); }
  });
});
