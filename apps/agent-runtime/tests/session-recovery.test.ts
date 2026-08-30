import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { RuntimeEventEnvelope, RuntimeStartRequest } from "@textbook-agent/agent-protocol";

import { ProviderRegistry } from "../src/providers/registry";
import type { AgentProvider, ProviderStartRequest } from "../src/providers/types";
import { RuntimeService } from "../src/runtime/RuntimeService";
import { SessionRegistry } from "../src/runtime/SessionRegistry";

function request(turnId: string): RuntimeStartRequest {
  return {
    session_id: "app-session",
    turn_id: turnId,
    input: [{ type: "text", text: turnId }],
    workspace_roots: ["C:\\vault"],
    provider: "claude",
    model: "claude-sonnet",
    permission_mode: "bypassPermissions",
    capability: "capability",
    callback_url: "http://127.0.0.1/events",
    idempotency_key: `start-${turnId}`,
  };
}

class RecordingProvider implements AgentProvider {
  readonly id = "claude";
  readonly starts: ProviderStartRequest[] = [];
  readonly stopped: string[] = [];
  readonly rewound: Array<[string, string]> = [];
  readonly forked: Array<[string, string]> = [];

  async *start(startRequest: ProviderStartRequest): AsyncIterable<RuntimeEventEnvelope> {
    this.starts.push(startRequest);
    const native = startRequest.native_session_id ?? "native-session";
    yield {
      event_id: `${startRequest.turn_id}-started`,
      session_id: startRequest.session_id,
      turn_id: startRequest.turn_id,
      sequence: 1,
      event_type: "turn_started",
      timestamp: "2026-08-28T00:00:00.000Z",
      payload: { native_session_id: native },
      idempotency_key: `${startRequest.turn_id}:1`,
    };
    yield {
      event_id: `${startRequest.turn_id}-text`,
      session_id: startRequest.session_id,
      turn_id: startRequest.turn_id,
      sequence: 2,
      event_type: "model_text_delta",
      timestamp: "2026-08-28T00:00:00.000Z",
      payload: { text: startRequest.turn_id },
      idempotency_key: `${startRequest.turn_id}:2`,
    };
  }

  async stop(sessionId: string) { this.stopped.push(sessionId); }
  async rewind(sessionId: string, checkpointId: string) { this.rewound.push([sessionId, checkpointId]); }
  async fork(sessionId: string, checkpointId: string) {
    this.forked.push([sessionId, checkpointId]);
    return { native_session_id: "native-fork" };
  }
  async health() { return { status: "ok" as const }; }
}

class DelayedProvider implements AgentProvider {
  readonly id = "claude";
  release: (() => void) | undefined;

  async *start(startRequest: ProviderStartRequest): AsyncIterable<RuntimeEventEnvelope> {
    yield {
      event_id: "00000000-0000-4000-8000-000000000001",
      session_id: startRequest.session_id,
      turn_id: startRequest.turn_id,
      sequence: 1,
      event_type: "turn_started",
      timestamp: "2026-08-29T00:00:00.000Z",
      payload: { native_session_id: "native-delayed" },
      idempotency_key: `${startRequest.turn_id}:1`,
    };
    await new Promise<void>(resolve => { this.release = resolve; });
    yield {
      event_id: "00000000-0000-4000-8000-000000000002",
      session_id: startRequest.session_id,
      turn_id: startRequest.turn_id,
      sequence: 2,
      event_type: "session_state",
      timestamp: "2026-08-29T00:00:01.000Z",
      payload: { state: "completed", native_session_id: "native-delayed" },
      idempotency_key: `${startRequest.turn_id}:2`,
    };
  }

  async stop() { this.release?.(); }
  async rewind() {}
  async fork() { return { native_session_id: "native-fork" }; }
  async health() { return { status: "ok" as const }; }
}

describe("Runtime turn acceptance", () => {
  it("returns after the first durable event while provider work continues", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-runtime-acceptance-"));
    try {
      const provider = new DelayedProvider();
      const providers = new ProviderRegistry();
      providers.register(provider);
      const published: RuntimeEventEnvelope[] = [];
      const service = new RuntimeService({
        providers,
        sessions: await SessionRegistry.open(join(root, "sessions.json")),
        eventSinkFactory: () => ({ publish: async event => { published.push(event); } }),
        uuid: () => "execution-delayed",
      });

      const pending = service.startTurn(request("turn-delayed"));
      const outcome = await Promise.race([
        pending.then(value => ({ kind: "accepted" as const, value })),
        new Promise<{ kind: "timeout" }>(resolve => setTimeout(() => resolve({ kind: "timeout" }), 50)),
      ]);

      provider.release?.();
      await service.waitForIdle("app-session");
      expect(outcome.kind).toBe("accepted");
      if (outcome.kind === "accepted") {
        expect(outcome.value).toEqual({
          execution_id: "execution-delayed",
          native_session_id: "native-delayed",
          accepted_sequence: 1,
        });
      }
      expect(published[0]?.event_type).toBe("turn_started");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("SessionRegistry and RuntimeService", () => {
  it("resumes a native Claude session with monotonic sequence after Runtime restart", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-session-registry-"));
    const statePath = join(root, "sessions.json");
    try {
      const provider = new RecordingProvider();
      const providers = new ProviderRegistry();
      providers.register(provider);
      const published: RuntimeEventEnvelope[] = [];

      const firstRuntime = new RuntimeService({
        providers,
        sessions: await SessionRegistry.open(statePath),
        eventSinkFactory: () => ({ publish: async event => { published.push(event); } }),
        uuid: () => "execution-1",
      });
      const first = await firstRuntime.startTurn(request("turn-1"));
      await firstRuntime.waitForIdle("app-session");

      const restartedRuntime = new RuntimeService({
        providers,
        sessions: await SessionRegistry.open(statePath),
        eventSinkFactory: () => ({ publish: async event => { published.push(event); } }),
        uuid: () => "execution-2",
      });
      const second = await restartedRuntime.resume(request("turn-2"));
      await restartedRuntime.waitForIdle("app-session");

      expect(second.native_session_id).toBe(first.native_session_id);
      expect(provider.starts[1].native_session_id).toBe(first.native_session_id);
      expect(second.accepted_sequence).toBeGreaterThan(first.accepted_sequence);
      expect(published.map(event => event.sequence)).toEqual([1, 2, 3, 4]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("delegates stop, rewind, and fork while persisting the forked native session", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-runtime-controls-"));
    try {
      const provider = new RecordingProvider();
      const providers = new ProviderRegistry();
      providers.register(provider);
      const sessions = await SessionRegistry.open(join(root, "sessions.json"));
      const service = new RuntimeService({
        providers,
        sessions,
        eventSinkFactory: () => ({ publish: async () => undefined }),
      });
      await service.startTurn(request("turn-1"));
      await service.waitForIdle("app-session");

      await service.stop("app-session");
      await service.rewind("app-session", "checkpoint-1");
      const fork = await service.fork("app-session", "checkpoint-1", "branch-session");

      expect(provider.stopped).toEqual(["app-session"]);
      expect(provider.rewound).toEqual([["app-session", "checkpoint-1"]]);
      expect(provider.forked).toEqual([["app-session", "checkpoint-1"]]);
      expect(fork).toEqual({ session_id: "branch-session", native_session_id: "native-fork" });
      expect(sessions.require("branch-session")).toMatchObject({ provider: "claude", native_session_id: "native-fork", sequence: 0 });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("SessionRegistry sequencing", () => {
  it("allocates unique monotonic sequences under concurrent callers", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-session-sequence-"));
    try {
      const sessions = await SessionRegistry.open(join(root, "sessions.json"));
      await sessions.upsert({
        session_id: "parallel-session",
        provider: "claude",
        native_session_id: "native-parallel",
        sequence: 0,
      });
      const allocated = await Promise.all(Array.from({ length: 20 }, () => sessions.nextSequence("parallel-session")));
      expect([...allocated].sort((left, right) => left - right)).toEqual(Array.from({ length: 20 }, (_, index) => index + 1));
      expect(sessions.require("parallel-session").sequence).toBe(20);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
