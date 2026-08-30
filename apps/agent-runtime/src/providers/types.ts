import type { RuntimeEventEnvelope, RuntimeStartRequest } from "@textbook-agent/agent-protocol";

export interface ProviderHealth {
  status: "ok" | "degraded" | "unavailable";
  detail?: string;
}

/**
 * Runtime-owned resume metadata is intentionally kept outside the public wire
 * contract. RuntimeService enriches the validated request after consulting the
 * durable SessionRegistry; providers must never trust a caller-supplied native id.
 */
export interface ProviderStartRequest extends RuntimeStartRequest {
  native_session_id?: string;
  mcp_servers?: Readonly<Record<string, unknown>>;
  skills?: readonly string[];
  subagents?: Readonly<Record<string, unknown>>;
}

export interface AgentProvider {
  readonly id: string;
  start(request: ProviderStartRequest, signal: AbortSignal): AsyncIterable<RuntimeEventEnvelope>;
  stop(sessionId: string): Promise<void>;
  rewind(sessionId: string, checkpointId: string): Promise<void>;
  fork(sessionId: string, checkpointId: string): Promise<{ native_session_id: string }>;
  health(): Promise<ProviderHealth>;
}
