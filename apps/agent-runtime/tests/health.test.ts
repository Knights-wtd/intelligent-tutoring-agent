import type { AddressInfo } from "node:net";

import { assertSupportedNodeVersion, loadRuntimeConfig } from "../src/config";
import { createRuntimeServer } from "../src/server";

const TEST_TOKEN = "test-runtime-token";

async function startServer() {
  const config = loadRuntimeConfig({
    AGENT_RUNTIME_HOST: "127.0.0.1",
    AGENT_RUNTIME_PORT: "0",
    AGENT_RUNTIME_TOKEN: TEST_TOKEN,
    AGENT_RUNTIME_SIDECAR_ROOT: "C:/tmp/agent-sidecars",
    AGENT_RUNTIME_MAX_CONTEXT_TOKENS: "1000000",
  }, "24.18.0");
  const server = createRuntimeServer(config, { upstreamCommit: "unvendored" });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, config.host, resolve);
  });
  const { port } = server.address() as AddressInfo;
  return {
    origin: `http://${config.host}:${port}`,
    close: () => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())),
  };
}

describe("agent runtime health server", () => {
  it("accepts Node.js 24 and rejects Node.js 22", () => {
    expect(() => assertSupportedNodeVersion("24.18.0")).not.toThrow();
    expect(() => assertSupportedNodeVersion("22.22.2")).toThrow(
      "Agent Runtime requires Node.js 24; received 22.22.2",
    );
  });

  it("loads an explicit Claude executable path", () => {
    const config = loadRuntimeConfig({
      AGENT_RUNTIME_TOKEN: TEST_TOKEN,
      AGENT_RUNTIME_SIDECAR_ROOT: "C:/tmp/agent-sidecars",
      AGENT_RUNTIME_CLAUDE_EXECUTABLE: "C:/tools/claude.exe",
    }, "24.18.0");
    expect(config.claudeExecutable).toBe("C:/tools/claude.exe");
  });

  it("serves loopback health without authentication", async () => {
    const runtime = await startServer();
    try {
      const response = await fetch(`${runtime.origin}/v1/health`);
      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual({
        status: "ok",
        protocol_version: "1.0",
        upstream_commit: "unvendored",
        node_version: process.versions.node,
      });
    } finally {
      await runtime.close();
    }
  });

  it("requires the runtime bearer token outside the health endpoint", async () => {
    const runtime = await startServer();
    try {
      const unauthenticated = await fetch(`${runtime.origin}/v1/diagnostics`);
      expect(unauthenticated.status).toBe(401);
      await expect(unauthenticated.json()).resolves.toEqual({
        error: { code: "unauthorized", message: "Unauthorized" },
      });

      const authenticated = await fetch(`${runtime.origin}/v1/diagnostics`, {
        headers: { authorization: `Bearer ${TEST_TOKEN}` },
      });
      expect(authenticated.status).toBe(404);
      await expect(authenticated.json()).resolves.toEqual({
        error: { code: "not_found", message: "Not found" },
      });
    } finally {
      await runtime.close();
    }
  });
});
