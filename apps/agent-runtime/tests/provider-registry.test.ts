import type { RuntimeEventEnvelope, RuntimeStartRequest } from "@textbook-agent/agent-protocol";

import { ProviderRegistry, ProviderUnavailableError } from "../src/providers/registry";
import type { AgentProvider } from "../src/providers/types";

function fakeProvider(id = "claude"): AgentProvider {
  return {
    id,
    async *start(_request: RuntimeStartRequest, _signal: AbortSignal): AsyncIterable<RuntimeEventEnvelope> {},
    async stop() {},
    async rewind() {},
    async fork() { return { native_session_id: "forked" }; },
    async health() { return { status: "ok" }; },
  };
}

describe("ProviderRegistry", () => {
  it("returns a registered enabled provider", () => {
    const registry = new ProviderRegistry();
    const provider = fakeProvider();
    registry.register(provider);
    expect(registry.require("claude")).toBe(provider);
  });

  it.each(["unknown", "disabled"])("raises provider_unavailable for %s providers", (kind) => {
    const registry = new ProviderRegistry();
    if (kind === "disabled") {
      registry.register(fakeProvider("disabled"), { enabled: false });
    }
    expect(() => registry.require(kind)).toThrow(ProviderUnavailableError);
    try {
      registry.require(kind);
    } catch (error) {
      expect(error).toMatchObject({ code: "provider_unavailable", providerId: kind });
    }
  });
});
