import type { Server } from "node:http";

import type { RuntimeStartRequest } from "@textbook-agent/agent-protocol";

import type { RuntimeConfig } from "./config";
import { FaroProvider } from "./providers/faro/FaroProvider";
import { ProviderRegistry } from "./providers/registry";
import { EventSink } from "./runtime/EventSink";
import { RuntimeService } from "./runtime/RuntimeService";
import { SessionRegistry } from "./runtime/SessionRegistry";
import { SidecarStore } from "./runtime/SidecarStore";
import { mapWorkspaceRoots } from "./runtime/workspace-roots";
import { verifyCapability } from "./security/capability";
import {
  createRuntimeServer,
  type RuntimeBuildInfo,
  type RuntimeControl,
} from "./server";

export interface RuntimeApplication {
  server: Server;
  service: RuntimeService;
  sessions: SessionRegistry;
  sidecars: SidecarStore;
}

export async function createRuntimeApplication(
  config: RuntimeConfig,
  buildInfo: RuntimeBuildInfo,
): Promise<RuntimeApplication> {
  const sessions = await SessionRegistry.open(config.sessionStatePath);
  const sidecars = new SidecarStore(config.sidecarRoot);
  const providers = new ProviderRegistry();
  providers.register(new FaroProvider({
    apiBaseUrl: config.faroApiBaseUrl,
    apiKey: config.faroApiKey,
    proxyUrl: config.faroProxyUrl,
    model: config.faroModel,
    timeoutSeconds: config.faroTimeoutSeconds,
  }));

  const service = new RuntimeService({
    providers,
    sessions,
    eventSinkFactory: (request: RuntimeStartRequest) => new EventSink({
      callbackUrl: request.callback_url,
      callbackToken: config.apiToken,
      inlineEventBytes: config.inlineEventBytes,
      sidecarStore: sidecars,
    }),
  });

  const mapRequest = (request: RuntimeStartRequest): RuntimeStartRequest => (
    config.vaultRoot
      ? { ...request, workspace_roots: mapWorkspaceRoots(request.workspace_roots, config.vaultRoot) }
      : request
  );

  const control: RuntimeControl = {
    start: request => service.startTurn(mapRequest(request)),
    stop: sessionId => service.stop(sessionId),
    resume: request => service.resume(mapRequest(request)),
    rewind: (sessionId, checkpointId) => service.rewind(sessionId, checkpointId),
    fork: (sessionId, checkpointId, forkSessionId) => service.fork(
      sessionId,
      checkpointId,
      forkSessionId,
    ),
    getSession: sessionId => service.getSession(sessionId),
    diagnostics: () => service.diagnostics(),
  };

  const server = createRuntimeServer(config, buildInfo, {
    control,
    verifyCapability: (token, sessionId) => {
      verifyCapability(token, { secret: config.capabilitySecret, sessionId });
    },
    readSidecar: (sidecarId, range) => sidecars.read(sidecarId, range),
  });
  return { server, service, sessions, sidecars };
}


