export type AgentKnowledgeBaseAction = "read" | "write" | "delete";

export type AgentToolCategory =
  | "vault"
  | "shell"
  | "web"
  | "mcp"
  | "skills"
  | "subagents";

export interface AgentKnowledgeBaseGrant {
  knowledge_base_id: string;
  actions: readonly AgentKnowledgeBaseAction[];
}

export interface AgentWorkspaceCapabilityPayload {
  version: string;
  user_id: string;
  session_id: string;
  grants: readonly AgentKnowledgeBaseGrant[];
  tool_categories: readonly AgentToolCategory[];
  vault_roots: readonly string[];
  issued_at: string;
  expires_at: string;
  nonce: string;
}
