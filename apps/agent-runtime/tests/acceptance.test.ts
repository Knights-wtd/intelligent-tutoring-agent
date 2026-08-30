import type { AddressInfo } from "node:net";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type {
  AgentWorkspaceCapabilityPayload,
  RuntimeEventEnvelope,
  RuntimeStartRequest,
  RuntimeStartResponse,
} from "@textbook-agent/agent-protocol";

import { loadRuntimeConfig } from "../src/config";
import type { McpServerConfig } from "../src/mcp/config";
import { McpManager } from "../src/mcp/McpManager";
import { ProviderRegistry } from "../src/providers/registry";
import type { AgentProvider, ProviderStartRequest } from "../src/providers/types";
import { EventSink } from "../src/runtime/EventSink";
import { RuntimeService } from "../src/runtime/RuntimeService";
import { SessionRegistry } from "../src/runtime/SessionRegistry";
import { SidecarStore } from "../src/runtime/SidecarStore";
import { CapabilityError, signCapability, verifyCapability } from "../src/security/capability";
import { SsrfGuard } from "../src/security/ssrf";
import { createRuntimeServer, type RuntimeControl } from "../src/server";
import { SkillRepository } from "../src/skills/SkillRepository";
import { SubagentManager, type SubagentEvent } from "../src/subagents/SubagentManager";
import { WebFetchTool } from "../src/tools/web/WebFetchTool";
import { WebSearchTool } from "../src/tools/web/WebSearchTool";
import { LocalHostVaultAdapter } from "../src/vault/HostVaultAdapter";

const RUNTIME_TOKEN = "acceptance-runtime-token";
const CAPABILITY_SECRET = "0123456789abcdef0123456789abcdef";
const SESSION_ID = "acceptance-session";

class AcceptanceProvider implements AgentProvider {
  readonly id = "acceptance";
  readonly starts: ProviderStartRequest[] = [];
  readonly stopped: string[] = [];
  readonly rewound: Array<[string, string]> = [];
  readonly forked: Array<[string, string]> = [];

  constructor(private readonly healthFailure = false) {}

  async *start(request: ProviderStartRequest): AsyncIterable<RuntimeEventEnvelope> {
    this.starts.push(request);
    const nativeSessionId = request.native_session_id ?? `native-${request.session_id}`;
    yield {
      event_id: `${request.turn_id}-started-${this.starts.length}`,
      session_id: request.session_id,
      turn_id: request.turn_id,
      sequence: 1,
      event_type: "turn_started",
      timestamp: "2026-08-29T00:00:00.000Z",
      payload: { native_session_id: nativeSessionId },
      idempotency_key: `${request.idempotency_key}:event:1`,
    };
  }

  async stop(sessionId: string): Promise<void> { this.stopped.push(sessionId); }
  async rewind(sessionId: string, checkpointId: string): Promise<void> {
    this.rewound.push([sessionId, checkpointId]);
  }
  async fork(sessionId: string, checkpointId: string): Promise<{ native_session_id: string }> {
    this.forked.push([sessionId, checkpointId]);
    return { native_session_id: `native-fork-${this.forked.length}` };
  }
  async health() {
    if (this.healthFailure) throw new Error("provider probe failed");
    return { status: "ok" as const };
  }
}

interface ControlHarness {
  origin: string;
  provider: AcceptanceProvider;
  published: RuntimeEventEnvelope[];
  sidecars: SidecarStore;
  capability: string;
  close(): Promise<void>;
}

async function startControlHarness(options: { healthFailure?: boolean } = {}): Promise<ControlHarness> {
  const root = await mkdtemp(join(tmpdir(), "agent-runtime-acceptance-"));
  const provider = new AcceptanceProvider(options.healthFailure);
  const providers = new ProviderRegistry();
  providers.register(provider);
  const sessions = await SessionRegistry.open(join(root, "state", "sessions.json"));
  const published: RuntimeEventEnvelope[] = [];
  let execution = 0;
  const service = new RuntimeService({
    providers,
    sessions,
    eventSinkFactory: () => ({ publish: async event => { published.push(event); } }),
    uuid: () => `execution-${++execution}`,
  });
  const sidecars = new SidecarStore(join(root, "sidecars"));
  const control: RuntimeControl = {
    start: request => service.startTurn(request),
    stop: sessionId => service.stop(sessionId),
    resume: request => service.resume(request),
    rewind: (sessionId, checkpointId) => service.rewind(sessionId, checkpointId),
    fork: (sessionId, checkpointId, forkSessionId) => service.fork(
      sessionId,
      checkpointId,
      forkSessionId,
    ),
    getSession: sessionId => service.getSession(sessionId),
    diagnostics: () => service.diagnostics(),
  };
  const config = loadRuntimeConfig({
    AGENT_RUNTIME_HOST: "127.0.0.1",
    AGENT_RUNTIME_PORT: "0",
    AGENT_RUNTIME_TOKEN: RUNTIME_TOKEN,
    AGENT_RUNTIME_CAPABILITY_SECRET: CAPABILITY_SECRET,
    AGENT_RUNTIME_SIDECAR_ROOT: join(root, "sidecars"),
    AGENT_RUNTIME_SESSION_STATE: join(root, "state", "sessions.json"),
  }, "24.18.0");
  const server = createRuntimeServer(config, { upstreamCommit: "acceptance" }, {
    control,
    verifyCapability: (token, sessionId) => {
      verifyCapability(token, { secret: CAPABILITY_SECRET, sessionId });
    },
    readSidecar: (sidecarId, range) => sidecars.read(sidecarId, range),
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, config.host, resolve);
  });
  const { port } = server.address() as AddressInfo;
  const capability = signCapability(capabilityPayload(SESSION_ID), CAPABILITY_SECRET);
  return {
    origin: `http://${config.host}:${port}`,
    provider,
    published,
    sidecars,
    capability,
    async close() {
      await new Promise<void>((resolve, reject) => {
        server.close(error => error ? reject(error) : resolve());
      });
      await rm(root, { recursive: true, force: true });
    },
  };
}

function capabilityPayload(sessionId: string): AgentWorkspaceCapabilityPayload {
  const now = Date.now();
  return {
    version: "1",
    user_id: "acceptance-user",
    session_id: sessionId,
    grants: [{ knowledge_base_id: "kb-authorized", actions: ["read", "write", "delete"] }],
    tool_categories: ["vault", "web", "shell", "mcp", "skills", "subagents"],
    vault_roots: ["C:/acceptance-vault"],
    issued_at: new Date(now - 60_000).toISOString(),
    expires_at: new Date(now + 10 * 60_000).toISOString(),
    nonce: "acceptance_nonce_0001",
  };
}

function startRequest(
  capability: string,
  turnId: string,
  idempotencyKey: string,
  overrides: Partial<RuntimeStartRequest> = {},
): RuntimeStartRequest {
  return {
    session_id: SESSION_ID,
    turn_id: turnId,
    input: [{ type: "text", text: `run ${turnId}` }],
    workspace_roots: ["C:/acceptance-vault"],
    provider: "acceptance",
    model: "acceptance-model",
    permission_mode: "bypassPermissions",
    capability,
    callback_url: "http://127.0.0.1:8000/runtime-events",
    idempotency_key: idempotencyKey,
    ...overrides,
  };
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    authorization: `Bearer ${RUNTIME_TOKEN}`,
    "content-type": "application/json",
    ...extra,
  };
}

async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: authHeaders(headers),
    body: JSON.stringify(body),
  });
}

async function json<T>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}

describe("Runtime acceptance", () => {
  it("processes a large Vault, repeated public Web calls, and tool events without product count caps", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-volume-acceptance-"));
    try {
      const config = loadRuntimeConfig({
        AGENT_RUNTIME_TOKEN: RUNTIME_TOKEN,
        AGENT_RUNTIME_SIDECAR_ROOT: join(root, "sidecars"),
        AGENT_RUNTIME_MAX_CONTEXT_TOKENS: "1000000",
      }, "24.18.0");
      expect(config.maxContextTokens).toBe(1_000_000);

      const vault = await LocalHostVaultAdapter.create(join(root, "vault"));
      for (let index = 0; index < 120; index += 1) {
        await vault.writeAtomic(
          `knowledge/concept-${index.toString().padStart(3, "0")}.md`,
          Buffer.from(`# Concept ${index}\n\nReusable workspace knowledge.\n`),
        );
      }
      const files = [];
      for await (const file of vault.list()) files.push(file);
      expect(files).toHaveLength(120);

      const fetched: string[] = [];
      const web = new WebFetchTool({
        guard: new SsrfGuard(async () => ["93.184.216.34"]),
        transport: async request => {
          fetched.push(request.url.toString());
          return {
            status: 200,
            headers: { "content-type": "text/plain" },
            body: Buffer.from(`public result ${fetched.length}`),
          };
        },
      });
      for (let index = 0; index < 30; index += 1) {
        const result = await web.fetch(`https://public.example/resource/${index}`);
        expect(result.status).toBe(200);
      }
      expect(fetched).toHaveLength(30);

      const search = new WebSearchTool(async () => Array.from({ length: 40 }, (_, index) => ({
        title: `Result ${index}`,
        url: `https://public.example/search/${index}`,
        snippet: `Snippet ${index}`,
      })));
      await expect(search.search("workspace agent acceptance")).resolves.toHaveLength(40);

      const delivered: RuntimeEventEnvelope[] = [];
      const sink = new EventSink({
        callbackUrl: "http://127.0.0.1:8000/runtime-events",
        post: async (_url, event) => {
          delivered.push(event);
          return {
            ok: true,
            status: 200,
            body: { persisted: true, accepted_sequence: event.sequence },
          };
        },
      });
      for (let sequence = 1; sequence <= 64; sequence += 1) {
        await sink.publish({
          event_id: `tool-${sequence}`,
          session_id: SESSION_ID,
          turn_id: "volume-turn",
          sequence,
          event_type: "tool_completed",
          timestamp: "2026-08-29T00:00:00.000Z",
          payload: { tool: "WebFetch", index: sequence },
          idempotency_key: `volume-turn:tool:${sequence}`,
        });
      }
      expect(delivered).toHaveLength(64);
      expect(sink.cursorFor(SESSION_ID)).toBe(64);

      const globalSkills = join(root, "global-skills");
      const vaultSkills = join(root, "vault", ".claude", "skills");
      await Promise.all(Array.from({ length: 75 }, async (_, index) => {
        const parent = index < 40 ? globalSkills : vaultSkills;
        const directory = join(parent, `skill-${index}`);
        await mkdir(directory, { recursive: true });
        await writeFile(
          join(directory, "SKILL.md"),
          `---\nname: skill-${index}\ndescription: Acceptance skill ${index}\n---\nRun safely.\n`,
          "utf8",
        );
      }));
      const skills = new SkillRepository({
        globalRoots: [globalSkills],
        vaultRoots: [join(root, "vault")],
      });
      await skills.refresh();
      expect(skills.list()).toHaveLength(75);

      let activeSubagents = 0;
      let peakSubagents = 0;
      const subagentEvents: SubagentEvent[] = [];
      const subagents = new SubagentManager({
        concurrency: 3,
        onEvent: event => { subagentEvents.push(event); },
        run: async request => {
          activeSubagents += 1;
          peakSubagents = Math.max(peakSubagents, activeSubagents);
          await new Promise<void>(resolve => setImmediate(resolve));
          activeSubagents -= 1;
          return { text: request.prompt };
        },
      });
      const subagentResults = await Promise.all(Array.from({ length: 30 }, (_, index) => (
        subagents.run({
          parentSessionId: SESSION_ID,
          parentToolCallId: `subagent-tool-${index}`,
          prompt: `inspect partition ${index}`,
        })
      )));
      expect(subagentResults).toHaveLength(30);
      expect(peakSubagents).toBe(3);
      expect(subagents.diagnostics()).toEqual({
        active: 0,
        queued: 0,
        completed: 30,
        failed: 0,
        concurrency: 3,
      });
      expect(subagentEvents.filter(event => event.type === "started")).toHaveLength(30);
      expect(subagentEvents.filter(event => event.type === "completed")).toHaveLength(30);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects capability escalation and realpath escapes outside the granted Vault", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-boundary-acceptance-"));
    const grantedRoot = join(root, "granted");
    const foreignRoot = join(root, "foreign");
    await mkdir(grantedRoot, { recursive: true });
    await mkdir(foreignRoot, { recursive: true });
    await writeFile(join(foreignRoot, "secret.md"), "foreign secret", "utf8");
    try {
      const token = signCapability({
        ...capabilityPayload(SESSION_ID),
        grants: [{ knowledge_base_id: "kb-authorized", actions: ["read"] }],
        tool_categories: ["vault", "web"],
        vault_roots: [grantedRoot],
      }, CAPABILITY_SECRET);
      const capability = verifyCapability(token, {
        secret: CAPABILITY_SECRET,
        sessionId: SESSION_ID,
      });
      expect(() => capability.requireGrant("kb-foreign", "read")).toThrow(CapabilityError);
      expect(() => capability.requireGrant("kb-authorized", "write")).toThrow(CapabilityError);
      expect(() => capability.requireTool("shell")).toThrow(CapabilityError);
      expect(() => verifyCapability(token, {
        secret: CAPABILITY_SECRET,
        sessionId: "another-session",
      })).toThrow(CapabilityError);

      const vault = await LocalHostVaultAdapter.create(grantedRoot);
      await symlink(
        foreignRoot,
        join(grantedRoot, "escape"),
        process.platform === "win32" ? "junction" : "dir",
      );
      await expect(vault.read("../foreign/secret.md")).rejects.toMatchObject({
        code: "path_outside_grant",
      });
      await expect(vault.read("escape/secret.md")).rejects.toMatchObject({
        code: "path_outside_grant",
      });
      await expect(vault.writeAtomic("escape/new.md", Buffer.from("denied"))).rejects.toMatchObject({
        code: "path_outside_grant",
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("keeps start, stop, resume, rewind, and fork mutations idempotent", async () => {
    const runtime = await startControlHarness();
    try {
      const firstRequest = startRequest(runtime.capability, "turn-1", "start-1");
      const [first, duplicateStart] = await Promise.all([
        postJson(`${runtime.origin}/v1/sessions/start`, firstRequest),
        postJson(`${runtime.origin}/v1/sessions/start`, firstRequest),
      ]);
      expect([first.status, duplicateStart.status]).toEqual([202, 202]);
      const firstBody = await json<RuntimeStartResponse>(first);
      const duplicateBody = await json<RuntimeStartResponse>(duplicateStart);
      expect(duplicateBody).toEqual(firstBody);
      expect(runtime.provider.starts).toHaveLength(1);

      const conflictingStart = await postJson(
        `${runtime.origin}/v1/sessions/start`,
        { ...firstRequest, model: "different-model" },
      );
      expect(conflictingStart.status).toBe(409);
      await expect(json<Record<string, unknown>>(conflictingStart)).resolves.toMatchObject({
        error: { code: "idempotency_conflict" },
      });

      const mutationHeaders = {
        "idempotency-key": "stop-1",
        "x-workspace-capability": runtime.capability,
      };
      const stop = await fetch(`${runtime.origin}/v1/sessions/${SESSION_ID}/stop`, {
        method: "POST",
        headers: authHeaders(mutationHeaders),
      });
      const duplicateStop = await fetch(`${runtime.origin}/v1/sessions/${SESSION_ID}/stop`, {
        method: "POST",
        headers: authHeaders(mutationHeaders),
      });
      expect([stop.status, duplicateStop.status]).toEqual([204, 204]);
      expect(runtime.provider.stopped).toEqual([SESSION_ID]);

      const resumeRequest = startRequest(runtime.capability, "turn-2", "resume-1");
      const resume = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/resume`,
        resumeRequest,
      );
      const duplicateResume = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/resume`,
        resumeRequest,
      );
      expect([resume.status, duplicateResume.status]).toEqual([202, 202]);
      expect(runtime.provider.starts).toHaveLength(2);
      expect(runtime.provider.starts[1]?.native_session_id).toBe(firstBody.native_session_id);

      const rewindHeaders = {
        "idempotency-key": "rewind-1",
        "x-workspace-capability": runtime.capability,
      };
      const rewind = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/rewind`,
        { checkpoint_id: "checkpoint-1" },
        rewindHeaders,
      );
      const duplicateRewind = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/rewind`,
        { checkpoint_id: "checkpoint-1" },
        rewindHeaders,
      );
      expect([rewind.status, duplicateRewind.status]).toEqual([204, 204]);
      expect(runtime.provider.rewound).toEqual([[SESSION_ID, "checkpoint-1"]]);

      const conflictingRewind = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/rewind`,
        { checkpoint_id: "checkpoint-2" },
        rewindHeaders,
      );
      expect(conflictingRewind.status).toBe(409);
      await expect(json<Record<string, unknown>>(conflictingRewind)).resolves.toMatchObject({
        error: { code: "idempotency_conflict" },
      });

      const forkHeaders = {
        "idempotency-key": "fork-1",
        "x-workspace-capability": runtime.capability,
      };
      const forkBody = { checkpoint_id: "checkpoint-1", fork_session_id: "acceptance-fork" };
      const fork = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/fork`,
        forkBody,
        forkHeaders,
      );
      const duplicateFork = await postJson(
        `${runtime.origin}/v1/sessions/${SESSION_ID}/fork`,
        forkBody,
        forkHeaders,
      );
      expect([fork.status, duplicateFork.status]).toEqual([201, 201]);
      expect(await json<Record<string, unknown>>(duplicateFork)).toEqual(
        await json<Record<string, unknown>>(fork),
      );
      expect(runtime.provider.forked).toEqual([[SESSION_ID, "checkpoint-1"]]);

      const sourceSession = await fetch(`${runtime.origin}/v1/sessions/${SESSION_ID}`, {
        headers: authHeaders(),
      });
      const forkSession = await fetch(`${runtime.origin}/v1/sessions/acceptance-fork`, {
        headers: authHeaders(),
      });
      expect(sourceSession.status).toBe(200);
      expect(forkSession.status).toBe(200);
      await expect(json<Record<string, unknown>>(sourceSession)).resolves.toMatchObject({
        session_id: SESSION_ID,
        native_session_id: firstBody.native_session_id,
        sequence: 2,
      });
      await expect(json<Record<string, unknown>>(forkSession)).resolves.toMatchObject({
        session_id: "acceptance-fork",
        sequence: 0,
      });
      expect(runtime.published.map(event => event.sequence)).toEqual([1, 2]);
    } finally {
      await runtime.close();
    }
  });

  it("retries event delivery and resumes the persisted native session after stop and restart", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-restart-acceptance-"));
    const statePath = join(root, "sessions.json");
    try {
      const provider = new AcceptanceProvider();
      const providers = new ProviderRegistry();
      providers.register(provider);
      const delivered: RuntimeEventEnvelope[] = [];
      let deliveryAttempts = 0;
      const firstSink = new EventSink({
        callbackUrl: "http://127.0.0.1:8000/runtime-events",
        sleep: async () => undefined,
        post: async (_url, event) => {
          deliveryAttempts += 1;
          if (deliveryAttempts === 1) return { ok: false, status: 503, body: undefined };
          delivered.push(event);
          return {
            ok: true,
            status: 200,
            body: { persisted: true, accepted_sequence: event.sequence },
          };
        },
      });
      const firstRuntime = new RuntimeService({
        providers,
        sessions: await SessionRegistry.open(statePath),
        eventSinkFactory: () => firstSink,
        uuid: () => "restart-execution-1",
      });
      const first = await firstRuntime.startTurn(
        startRequest("capability", "restart-turn-1", "restart-1"),
      );
      await firstRuntime.stop(SESSION_ID);

      const secondSink = new EventSink({
        callbackUrl: "http://127.0.0.1:8000/runtime-events",
        post: async (_url, event) => {
          delivered.push(event);
          return {
            ok: true,
            status: 200,
            body: { persisted: true, accepted_sequence: event.sequence },
          };
        },
      });
      const restartedRuntime = new RuntimeService({
        providers,
        sessions: await SessionRegistry.open(statePath),
        eventSinkFactory: () => secondSink,
        uuid: () => "restart-execution-2",
      });
      const resumed = await restartedRuntime.resume(
        startRequest("capability", "restart-turn-2", "restart-2"),
      );

      expect(deliveryAttempts).toBe(2);
      expect(provider.stopped).toEqual([SESSION_ID]);
      expect(provider.starts[1]?.native_session_id).toBe(first.native_session_id);
      expect(resumed.native_session_id).toBe(first.native_session_id);
      expect(resumed.accepted_sequence).toBeGreaterThan(first.accepted_sequence);
      expect(delivered.map(event => event.sequence)).toEqual([1, 2]);
      await secondSink.publish(delivered[1]!);
      expect(delivered.map(event => event.sequence)).toEqual([1, 2]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("revalidates SSRF redirects and isolates degraded MCP servers across supported transports", async () => {
    const web = new WebFetchTool({
      guard: new SsrfGuard(async hostname => (
        hostname === "public.example" ? ["93.184.216.34"] : ["127.0.0.1"]
      )),
      transport: async () => ({
        status: 302,
        headers: { location: "http://private.example/secret" },
        body: Buffer.alloc(0),
      }),
    });
    await expect(web.fetch("https://public.example/start")).rejects.toMatchObject({
      code: "ssrf_blocked",
    });

    const closed: string[] = [];
    const manager = new McpManager(async config => {
      if (config.id === "offline") throw new Error("MCP server unavailable");
      return {
        tools: [`${config.id}:inspect`],
        close: async () => { closed.push(config.id); },
      };
    });
    const configs: McpServerConfig[] = [
      { id: "stdio", transport: "stdio", command: "node", args: [] },
      { id: "sse", transport: "sse", url: "https://mcp.example/sse" },
      { id: "http", transport: "streamable-http", url: "https://mcp.example/rpc" },
    ];
    for (const config of configs) {
      await expect(manager.connect(config)).resolves.toMatchObject({ status: "connected" });
    }
    await expect(manager.connect({
      id: "offline",
      transport: "sse",
      url: "https://offline.example/sse",
    })).resolves.toMatchObject({ status: "degraded", error: "MCP server unavailable" });
    expect(manager.listTools()).toEqual([
      "stdio:inspect",
      "sse:inspect",
      "http:inspect",
    ]);
    expect(manager.diagnostics()).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "offline", status: "degraded" }),
      expect.objectContaining({ id: "stdio", status: "connected" }),
      expect.objectContaining({ id: "sse", status: "connected" }),
      expect.objectContaining({ id: "http", status: "connected" }),
    ]));
    await manager.disconnect("sse");
    expect(closed).toEqual(["sse"]);
    expect(manager.listTools()).toEqual(["stdio:inspect", "http:inspect"]);
  });

  it("returns degraded diagnostics while health and session control remain responsive", async () => {
    const runtime = await startControlHarness({ healthFailure: true });
    try {
      const diagnostics = await fetch(`${runtime.origin}/v1/diagnostics`, {
        headers: authHeaders(),
      });
      expect(diagnostics.status).toBe(200);
      await expect(json<Record<string, unknown>>(diagnostics)).resolves.toMatchObject({
        status: "degraded",
        providers: [{
          id: "acceptance",
          enabled: true,
          status: "unavailable",
          detail: "provider probe failed",
        }],
      });

      const health = await fetch(`${runtime.origin}/v1/health`);
      expect(health.status).toBe(200);
      await expect(json<Record<string, unknown>>(health)).resolves.toMatchObject({ status: "ok" });

      const start = await postJson(
        `${runtime.origin}/v1/sessions/start`,
        startRequest(runtime.capability, "degraded-turn", "degraded-start"),
      );
      expect(start.status).toBe(202);
      expect(runtime.provider.starts).toHaveLength(1);
      const session = await fetch(`${runtime.origin}/v1/sessions/${SESSION_ID}`, {
        headers: authHeaders(),
      });
      expect(session.status).toBe(200);
    } finally {
      await runtime.close();
    }
  });

  it("serves complete sidecar data through authenticated byte ranges", async () => {
    const runtime = await startControlHarness();
    try {
      const payload = { text: "abcdefghijklmnopqrstuvwxyz", nested: { complete: true } };
      const descriptor = await runtime.sidecars.putJson(SESSION_ID, "large-output", payload);
      const complete = await readFile(runtime.sidecars.pathFor(descriptor.sidecar_id));
      expect(JSON.parse(complete.toString("utf8"))).toEqual(payload);
      const start = 7;
      const end = 26;
      const response = await fetch(
        `${runtime.origin}/v1/sidecars/${encodeURIComponent(descriptor.sidecar_id)}`,
        { headers: authHeaders({ range: `bytes=${start}-${end}` }) },
      );
      expect(response.status).toBe(206);
      expect(response.headers.get("accept-ranges")).toBe("bytes");
      expect(response.headers.get("content-range")).toBe(
        `bytes ${start}-${end}/${complete.byteLength}`,
      );
      expect(Buffer.from(await response.arrayBuffer())).toEqual(complete.subarray(start, end + 1));

      const blockedRoot = join(runtime.sidecars.root, "blocked-root");
      await writeFile(blockedRoot, "not a directory", "utf8");
      let posted = false;
      const diskFaultSink = new EventSink({
        callbackUrl: "http://127.0.0.1:8000/runtime-events",
        inlineEventBytes: 1,
        sidecarStore: new SidecarStore(blockedRoot),
        post: async () => {
          posted = true;
          return { ok: true, status: 200, body: { persisted: true, accepted_sequence: 1 } };
        },
      });
      await expect(diskFaultSink.publish({
        event_id: "disk-fault",
        session_id: SESSION_ID,
        turn_id: "sidecar-turn",
        sequence: 1,
        event_type: "tool_completed",
        timestamp: "2026-08-29T00:00:00.000Z",
        payload: { output: "large output must not be silently truncated" },
        idempotency_key: "sidecar-turn:disk-fault",
      })).rejects.toHaveProperty("code");
      expect(posted).toBe(false);
    } finally {
      await runtime.close();
    }
  });
});
