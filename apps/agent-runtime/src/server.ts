import { createHash, timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import {
  RUNTIME_PROTOCOL_VERSION,
  type RuntimeHealthResponse,
  type RuntimeStartRequest,
  type RuntimeStartResponse,
} from "@textbook-agent/agent-protocol";

import type { RuntimeConfig } from "./config";

export interface RuntimeBuildInfo {
  upstreamCommit: string;
}

export interface RuntimeSessionView {
  session_id: string;
  provider: string;
  native_session_id: string;
  sequence: number;
  updated_at?: string;
}

export interface RuntimeControl {
  start(request: RuntimeStartRequest): Promise<RuntimeStartResponse>;
  stop(sessionId: string): Promise<void>;
  resume(request: RuntimeStartRequest): Promise<RuntimeStartResponse>;
  rewind(sessionId: string, checkpointId: string): Promise<void>;
  fork(
    sessionId: string,
    checkpointId: string,
    forkSessionId: string,
  ): Promise<{ session_id: string; native_session_id: string }>;
  getSession(sessionId: string): RuntimeSessionView | undefined;
  diagnostics(): Promise<Record<string, unknown>>;
}

export interface SidecarReadResult {
  bytes: Buffer;
  totalSize: number;
  mediaType: string;
}

export interface RuntimeServerDependencies {
  control: RuntimeControl;
  verifyCapability(token: string, sessionId: string): void;
  readSidecar(
    sidecarId: string,
    range?: { start: number; end?: number },
  ): Promise<SidecarReadResult>;
}

interface CachedMutation {
  bodyHash: string;
  promise: Promise<HttpResult>;
}

interface HttpResult {
  status: number;
  body?: unknown;
}

const MAX_JSON_BODY_BYTES = 16 * 1024 * 1024;

export function createRuntimeServer(
  config: RuntimeConfig,
  buildInfo: RuntimeBuildInfo,
  dependencies?: RuntimeServerDependencies,
): Server {
  const idempotency = new Map<string, CachedMutation>();
  return createServer((request, response) => {
    void handleRequest(request, response, config, buildInfo, dependencies, idempotency)
      .catch(error => sendError(response, error));
  });
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  config: RuntimeConfig,
  buildInfo: RuntimeBuildInfo,
  dependencies: RuntimeServerDependencies | undefined,
  idempotency: Map<string, CachedMutation>,
): Promise<void> {
  const url = new URL(request.url ?? "/", "http://runtime.local");
  if (request.method === "GET" && url.pathname === "/v1/health") {
    sendJson(response, 200, {
      status: "ok",
      protocol_version: RUNTIME_PROTOCOL_VERSION,
      upstream_commit: buildInfo.upstreamCommit,
      node_version: process.versions.node,
    } satisfies RuntimeHealthResponse);
    return;
  }

  if (!hasBearerToken(request, config.apiToken)) {
    sendJson(response, 401, { error: { code: "unauthorized", message: "Unauthorized" } });
    return;
  }
  if (!dependencies) {
    sendNotFound(response);
    return;
  }

  if (request.method === "POST" && url.pathname === "/v1/sessions/start") {
    const body = await readJsonObject(request);
    const startRequest = parseStartRequest(body);
    verifyCapability(dependencies, startRequest.capability, startRequest.session_id);
    const result = await idempotentMutation(
      idempotency,
      `start:${startRequest.idempotency_key}`,
      body,
      async () => ({ status: 202, body: await dependencies.control.start(startRequest) }),
    );
    sendResult(response, result);
    return;
  }

  const sessionMatch = /^\/v1\/sessions\/([^/]+)(?:\/(stop|resume|rewind|fork))?$/.exec(url.pathname);
  if (sessionMatch) {
    const sessionId = decodePathComponent(sessionMatch[1] ?? "");
    const action = sessionMatch[2];
    if (!action && request.method === "GET") {
      const session = dependencies.control.getSession(sessionId);
      if (!session) sendJson(response, 404, { error: { code: "session_not_found", message: "Session not found" } });
      else sendJson(response, 200, session);
      return;
    }
    if (request.method === "POST" && action) {
      if (action === "resume") {
        const body = await readJsonObject(request);
        const startRequest = parseStartRequest(body);
        if (startRequest.session_id !== sessionId) throw invalidRequest("Session id does not match request path");
        verifyCapability(dependencies, startRequest.capability, sessionId);
        const result = await idempotentMutation(
          idempotency,
          `resume:${sessionId}:${startRequest.idempotency_key}`,
          body,
          async () => ({ status: 202, body: await dependencies.control.resume(startRequest) }),
        );
        sendResult(response, result);
        return;
      }

      const metadata = readMutationMetadata(request, sessionId, dependencies);
      const body = action === "stop" ? {} : await readJsonObject(request);
      const cacheKey = `${action}:${sessionId}:${metadata.idempotencyKey}`;
      const result = await idempotentMutation(idempotency, cacheKey, body, async () => {
        if (action === "stop") {
          await dependencies.control.stop(sessionId);
          return { status: 204 };
        }
        const checkpointId = requireString(body.checkpoint_id, "checkpoint_id");
        if (action === "rewind") {
          await dependencies.control.rewind(sessionId, checkpointId);
          return { status: 204 };
        }
        const forkSessionId = requireString(body.fork_session_id, "fork_session_id");
        return { status: 201, body: await dependencies.control.fork(sessionId, checkpointId, forkSessionId) };
      });
      sendResult(response, result);
      return;
    }
  }

  if (request.method === "GET" && url.pathname === "/v1/diagnostics") {
    sendJson(response, 200, await dependencies.control.diagnostics());
    return;
  }

  if (request.method === "GET" && url.pathname.startsWith("/v1/sidecars/")) {
    const sidecarId = decodePathComponent(url.pathname.slice("/v1/sidecars/".length));
    const requestedRange = parseRange(request.headers.range);
    const result = await dependencies.readSidecar(sidecarId, requestedRange);
    const actualStart = requestedRange?.start ?? 0;
    const actualEnd = actualStart + result.bytes.byteLength - 1;
    const status = requestedRange ? 206 : 200;
    response.writeHead(status, {
      "accept-ranges": "bytes",
      "cache-control": "no-store",
      "content-length": result.bytes.byteLength,
      "content-type": result.mediaType,
      ...(requestedRange ? { "content-range": `bytes ${actualStart}-${actualEnd}/${result.totalSize}` } : {}),
    });
    response.end(result.bytes);
    return;
  }

  sendNotFound(response);
}

function readMutationMetadata(
  request: IncomingMessage,
  sessionId: string,
  dependencies: RuntimeServerDependencies,
): { idempotencyKey: string } {
  const idempotencyKey = singleHeader(request, "idempotency-key");
  const capability = singleHeader(request, "x-workspace-capability");
  if (!idempotencyKey || !capability) {
    throw invalidRequest("Mutation requires Idempotency-Key and X-Workspace-Capability headers");
  }
  verifyCapability(dependencies, capability, sessionId);
  return { idempotencyKey };
}

function verifyCapability(
  dependencies: RuntimeServerDependencies,
  token: string,
  sessionId: string,
): void {
  try {
    dependencies.verifyCapability(token, sessionId);
  } catch (error) {
    const denied = new Error(error instanceof Error ? error.message : "Capability denied");
    Object.assign(denied, { status: 403, code: "capability_denied" });
    throw denied;
  }
}

async function idempotentMutation(
  cache: Map<string, CachedMutation>,
  key: string,
  body: Record<string, unknown>,
  operation: () => Promise<HttpResult>,
): Promise<HttpResult> {
  const bodyHash = createHash("sha256").update(stableJson(body)).digest("hex");
  const existing = cache.get(key);
  if (existing) {
    if (existing.bodyHash !== bodyHash) {
      const conflict = new Error("Idempotency key was already used with a different request");
      Object.assign(conflict, { status: 409, code: "idempotency_conflict" });
      throw conflict;
    }
    return existing.promise;
  }
  const promise = operation();
  cache.set(key, { bodyHash, promise });
  try {
    return await promise;
  } catch (error) {
    cache.delete(key);
    throw error;
  }
}

function parseStartRequest(body: Record<string, unknown>): RuntimeStartRequest {
  for (const key of [
    "session_id", "turn_id", "provider", "model", "capability", "callback_url", "idempotency_key",
  ] as const) requireString(body[key], key);
  if (body.permission_mode !== "bypassPermissions") throw invalidRequest("permission_mode must be bypassPermissions");
  if (!Array.isArray(body.input) || !Array.isArray(body.workspace_roots)) {
    throw invalidRequest("input and workspace_roots must be arrays");
  }
  return body as unknown as RuntimeStartRequest;
}

async function readJsonObject(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.byteLength;
    if (size > MAX_JSON_BODY_BYTES) {
      const error = invalidRequest("JSON request body is too large");
      Object.assign(error, { status: 413, code: "payload_too_large" });
      throw error;
    }
    chunks.push(bytes);
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("not object");
    return value as Record<string, unknown>;
  } catch {
    throw invalidRequest("Request body must be a JSON object");
  }
}

function parseRange(value: string | undefined): { start: number; end?: number } | undefined {
  if (!value) return undefined;
  const match = /^bytes=(\d+)-(\d*)$/.exec(value);
  if (!match) throw invalidRequest("Only one explicit byte range is supported");
  const start = Number(match[1]);
  const end = match[2] ? Number(match[2]) : undefined;
  if (!Number.isSafeInteger(start) || start < 0 || (end !== undefined && (!Number.isSafeInteger(end) || end < start))) {
    throw invalidRequest("Invalid byte range");
  }
  return end === undefined ? { start } : { start, end };
}

function singleHeader(request: IncomingMessage, name: string): string | undefined {
  const value = request.headers[name];
  return Array.isArray(value) ? value[0] : value;
}

function requireString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) throw invalidRequest(`${name} is required`);
  return value;
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map(key => `${JSON.stringify(key)}:${stableJson(object[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function invalidRequest(message: string): Error {
  const error = new Error(message);
  Object.assign(error, { status: 400, code: "invalid_request" });
  return error;
}

function decodePathComponent(value: string): string {
  try { return decodeURIComponent(value); }
  catch { throw invalidRequest("Path contains invalid encoding"); }
}

function hasBearerToken(request: IncomingMessage, expectedToken: string): boolean {
  const authorization = request.headers.authorization;
  if (!authorization?.startsWith("Bearer ")) return false;
  const provided = Buffer.from(authorization.slice("Bearer ".length), "utf8");
  const expected = Buffer.from(expectedToken, "utf8");
  return provided.length === expected.length && timingSafeEqual(provided, expected);
}

function sendResult(response: ServerResponse, result: HttpResult): void {
  if (result.status === 204) {
    response.writeHead(204, { "cache-control": "no-store" });
    response.end();
  } else {
    sendJson(response, result.status, result.body ?? {});
  }
}

function sendError(response: ServerResponse, error: unknown): void {
  if (response.headersSent) {
    response.destroy();
    return;
  }
  const value = error as { status?: unknown; code?: unknown; message?: unknown };
  const status = typeof value?.status === "number" ? value.status : 500;
  const code = typeof value?.code === "string" ? value.code : "runtime_error";
  if (status >= 500) {
    const name = error instanceof Error ? error.name : typeof error;
    const detail = error instanceof Error ? error.message : "Unknown runtime failure";
    console.error(`[agent-runtime] request failed code=${code} name=${name}: ${detail}`);
  }
  const message = status >= 500 ? "Runtime request failed" : String(value?.message ?? "Request failed");
  sendJson(response, status, { error: { code, message } });
}

function sendNotFound(response: ServerResponse): void {
  sendJson(response, 404, { error: { code: "not_found", message: "Not found" } });
}

function sendJson(response: ServerResponse, statusCode: number, body: unknown): void {
  const encoded = JSON.stringify(body);
  response.writeHead(statusCode, {
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(encoded),
    "content-type": "application/json; charset=utf-8",
  });
  response.end(encoded);
}
