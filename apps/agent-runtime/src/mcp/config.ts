export type McpServerConfig =
  | { id: string; transport: "stdio"; command: string; args?: readonly string[]; environment?: Readonly<Record<string, string>> }
  | { id: string; transport: "sse" | "streamable-http"; url: string; headers?: Readonly<Record<string, string>> };

export function validateMcpConfig(config: McpServerConfig): McpServerConfig {
  if (!config.id.trim()) throw new TypeError("MCP server id is required");
  if (config.transport === "stdio" && !config.command.trim()) throw new TypeError("MCP stdio command is required");
  if (config.transport !== "stdio") {
    const url = new URL(config.url);
    if (url.protocol !== "https:" && url.protocol !== "http:") throw new TypeError("MCP URL must use HTTP(S)");
  }
  return config;
}
