import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { performance } from "node:perf_hooks";

import { SsrfGuard } from "../security/ssrf";
import { validateMcpConfig, type McpServerConfig } from "./config";

export interface McpConnection { tools: readonly string[]; close(): Promise<void>; }
export type McpConnector = (config: McpServerConfig) => Promise<McpConnection>;
export interface McpServerStatus {
  id: string;
  transport: McpServerConfig["transport"];
  status: "connected" | "degraded" | "disconnected";
  durationMs: number;
  error?: string;
}

export class McpManager {
  private readonly connections = new Map<string, McpConnection>();
  private readonly statuses = new Map<string, McpServerStatus>();

  constructor(private readonly connector: McpConnector = createDefaultMcpConnector()) {}

  async connect(input: McpServerConfig): Promise<McpServerStatus> {
    const config = validateMcpConfig(input);
    const started = performance.now();
    try {
      await this.connections.get(config.id)?.close();
      const connection = await this.connector(config);
      this.connections.set(config.id, connection);
      const status: McpServerStatus = {
        id: config.id,
        transport: config.transport,
        status: "connected",
        durationMs: performance.now() - started,
      };
      this.statuses.set(config.id, status);
      return status;
    } catch (error) {
      this.connections.delete(config.id);
      const status: McpServerStatus = {
        id: config.id,
        transport: config.transport,
        status: "degraded",
        durationMs: performance.now() - started,
        error: error instanceof Error ? error.message : String(error),
      };
      this.statuses.set(config.id, status);
      return status;
    }
  }

  async disconnect(id: string): Promise<void> {
    await this.connections.get(id)?.close();
    this.connections.delete(id);
    const current = this.statuses.get(id);
    if (current) this.statuses.set(id, { ...current, status: "disconnected" });
  }

  listTools(): readonly string[] {
    return [...this.connections.values()].flatMap(connection => [...connection.tools]);
  }

  diagnostics(): readonly McpServerStatus[] {
    return [...this.statuses.values()];
  }
}

export function createDefaultMcpConnector(ssrf = new SsrfGuard()): McpConnector {
  return async config => {
    const client = new Client(
      { name: "textbook-agent-runtime", version: "0.1.0" },
      { capabilities: {} },
    );
    const transport = config.transport === "stdio"
      ? new StdioClientTransport({
          command: config.command,
          args: [...(config.args ?? [])],
          env: { ...stringEnvironment(process.env), ...(config.environment ?? {}) },
          stderr: "pipe",
        })
      : await createNetworkTransport(config, ssrf);
    try {
      await client.connect(transport);
      const tools = (await client.listTools()).tools.map(tool => tool.name);
      return {
        tools,
        close: async () => { await client.close(); },
      };
    } catch (error) {
      await client.close().catch(() => undefined);
      throw error;
    }
  };
}

async function createNetworkTransport(
  config: Extract<McpServerConfig, { transport: "sse" | "streamable-http" }>,
  ssrf: SsrfGuard,
): Promise<SSEClientTransport | StreamableHTTPClientTransport> {
  const resolved = await ssrf.resolve(config.url);
  const requestInit = config.headers ? { headers: { ...config.headers } } : undefined;
  return config.transport === "sse"
    ? new SSEClientTransport(resolved.url, { requestInit })
    : new StreamableHTTPClientTransport(resolved.url, { requestInit });
}

function stringEnvironment(
  environment: NodeJS.ProcessEnv,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(environment).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );
}
