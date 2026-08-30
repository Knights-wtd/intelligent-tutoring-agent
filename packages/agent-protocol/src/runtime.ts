export const RUNTIME_PROTOCOL_VERSION = "1.0" as const;

export type RuntimeInputBlock =
  | { readonly type: "text"; readonly text: string }
  | { readonly type: "image"; readonly media_type: string; readonly data: string };

export interface RuntimeStartRequest {
  session_id: string;
  turn_id: string;
  input: readonly RuntimeInputBlock[];
  workspace_roots: readonly string[];
  provider: string;
  model: string;
  permission_mode: "bypassPermissions";
  capability: string;
  callback_url: string;
  idempotency_key: string;
}

export interface RuntimeStartResponse {
  execution_id: string;
  native_session_id: string;
  accepted_sequence: number;
}

export interface RuntimeHealthResponse {
  status: "ok";
  protocol_version: typeof RUNTIME_PROTOCOL_VERSION;
  upstream_commit: string;
  node_version: string;
}
