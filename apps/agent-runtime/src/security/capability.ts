import { createHmac, timingSafeEqual } from "node:crypto";

import type {
  AgentKnowledgeBaseAction,
  AgentKnowledgeBaseGrant,
  AgentToolCategory,
  AgentWorkspaceCapabilityPayload,
} from "@textbook-agent/agent-protocol";

const ACTIONS = new Set<AgentKnowledgeBaseAction>(["read", "write", "delete"]);
const TOOLS = new Set<AgentToolCategory>(["vault", "shell", "web", "mcp", "skills", "subagents"]);
const NONCE_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;

export class CapabilityError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "CapabilityError";
  }
}

export class VerifiedCapability {
  constructor(readonly payload: AgentWorkspaceCapabilityPayload) {}

  requireGrant(knowledgeBaseId: string, action: AgentKnowledgeBaseAction): AgentKnowledgeBaseGrant {
    const grant = this.payload.grants.find(item => item.knowledge_base_id === knowledgeBaseId);
    if (!grant || !grant.actions.includes(action)) {
      throw new CapabilityError("capability_denied", `Capability does not grant ${action} on ${knowledgeBaseId}`);
    }
    return grant;
  }

  requireTool(category: AgentToolCategory): void {
    if (!this.payload.tool_categories.includes(category)) {
      throw new CapabilityError("capability_denied", `Capability does not grant tool category ${category}`);
    }
  }
}

export interface VerifyCapabilityOptions {
  secret: string | Buffer;
  sessionId: string;
  now?: Date;
}

export function signCapability(payload: AgentWorkspaceCapabilityPayload, secret: string | Buffer): string {
  const encoded = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  return `${encoded}.${signature(encoded, secret).toString("base64url")}`;
}

export function verifyCapability(token: string, options: VerifyCapabilityOptions): VerifiedCapability {
  const parts = token.split(".");
  if (parts.length !== 2 || !parts[0] || !parts[1]) fail("capability_invalid", "Malformed capability");
  const expected = signature(parts[0], options.secret);
  let provided: Buffer;
  try { provided = Buffer.from(parts[1], "base64url"); } catch { fail("capability_invalid", "Malformed signature"); }
  if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) fail("capability_invalid", "Invalid capability signature");

  let payload: AgentWorkspaceCapabilityPayload;
  try { payload = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8")) as AgentWorkspaceCapabilityPayload; }
  catch { fail("capability_invalid", "Malformed capability payload"); }
  validatePayload(payload);
  if (payload.session_id !== options.sessionId) fail("capability_session_mismatch", "Capability is bound to another session");
  const now = (options.now ?? new Date()).getTime();
  const issued = Date.parse(payload.issued_at);
  const expires = Date.parse(payload.expires_at);
  if (!Number.isFinite(issued) || !Number.isFinite(expires) || issued > expires) fail("capability_invalid", "Capability timestamps are invalid");
  if (now < issued - 60_000) fail("capability_not_yet_valid", "Capability is not active yet");
  if (now >= expires) fail("capability_expired", "Capability has expired");
  return new VerifiedCapability(payload);
}

function validatePayload(payload: AgentWorkspaceCapabilityPayload): void {
  if (!payload || typeof payload !== "object") fail("capability_invalid", "Capability payload must be an object");
  for (const key of ["version", "user_id", "session_id", "issued_at", "expires_at", "nonce"] as const) {
    if (typeof payload[key] !== "string" || payload[key].length === 0) fail("capability_invalid", `Capability ${key} is required`);
  }
  if (!NONCE_PATTERN.test(payload.nonce)) fail("capability_invalid", "Capability nonce is invalid");
  if (!Array.isArray(payload.grants) || !Array.isArray(payload.tool_categories) || !Array.isArray(payload.vault_roots)) fail("capability_invalid", "Capability arrays are invalid");
  for (const grant of payload.grants) {
    if (!grant || typeof grant.knowledge_base_id !== "string" || !Array.isArray(grant.actions) || grant.actions.some((action: AgentKnowledgeBaseAction) => !ACTIONS.has(action))) fail("capability_invalid", "Capability grant is invalid");
  }
  if (payload.tool_categories.some(tool => !TOOLS.has(tool))) fail("capability_invalid", "Capability tool category is invalid");
  if (payload.vault_roots.some(root => typeof root !== "string" || root.length === 0)) fail("capability_invalid", "Capability vault root is invalid");
}

function signature(encodedPayload: string, secret: string | Buffer): Buffer {
  return createHmac("sha256", secret).update(encodedPayload, "utf8").digest();
}

function fail(code: string, message: string): never { throw new CapabilityError(code, message); }
