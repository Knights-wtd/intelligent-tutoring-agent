import { McpManager } from "../src/mcp/McpManager";
import type { McpServerConfig } from "../src/mcp/config";

it.each(["stdio", "sse", "streamable-http"] as const)("connects MCP transport %s", async transport => {
  const manager = new McpManager(async config => ({ close: async () => {}, tools: [`${config.id}:tool`] }));
  const config: McpServerConfig = transport === "stdio"
    ? { id: `server-${transport}`, transport, command: "node", args: [] }
    : { id: `server-${transport}`, transport, url: "https://mcp.example/rpc" };
  const status = await manager.connect(config);
  expect(status.status).toBe("connected");
  expect(manager.listTools()).toContain(`server-${transport}:tool`);
});

it("degrades only the failed MCP server", async () => {
  const manager = new McpManager(async config => { if (config.id === "bad") throw new Error("offline"); return { close: async () => {}, tools: ["ok:tool"] }; });
  await manager.connect({ id: "ok", transport: "stdio", command: "node", args: [] });
  await expect(manager.connect({ id: "bad", transport: "sse", url: "https://mcp.example/sse" })).resolves.toMatchObject({ status: "degraded" });
  expect(manager.listTools()).toEqual(["ok:tool"]);
});
