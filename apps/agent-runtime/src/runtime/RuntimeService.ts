import { randomUUID } from "node:crypto";

import type {
  RuntimeEventEnvelope,
  RuntimeStartRequest,
  RuntimeStartResponse,
} from "@textbook-agent/agent-protocol";

import type { ProviderRegistry } from "../providers/registry";
import type { ProviderStartRequest } from "../providers/types";
import type { SessionRegistry } from "./SessionRegistry";

export interface RuntimeEventPublisher {
  publish(event: RuntimeEventEnvelope): Promise<void>;
}

export type EventSinkFactory = (request: RuntimeStartRequest) => RuntimeEventPublisher;

export interface RuntimeServiceOptions {
  providers: ProviderRegistry;
  sessions: SessionRegistry;
  eventSinkFactory: EventSinkFactory;
  uuid?: () => string;
}

export class RuntimeSessionBusyError extends Error {
  readonly code = "session_busy" as const;

  constructor(readonly sessionId: string) {
    super(`Runtime session ${sessionId} already has an active turn`);
    this.name = "RuntimeSessionBusyError";
  }
}

export class RuntimeService {
  private readonly active = new Map<string, AbortController>();
  private readonly background = new Map<string, Promise<void>>();
  private readonly uuid: () => string;

  constructor(private readonly options: RuntimeServiceOptions) {
    this.uuid = options.uuid ?? randomUUID;
  }

  async startTurn(request: RuntimeStartRequest, externalSignal?: AbortSignal): Promise<RuntimeStartResponse> {
    if (request.permission_mode !== "bypassPermissions") {
      throw new TypeError("Runtime requires permission_mode=bypassPermissions");
    }
    if (this.active.has(request.session_id)) throw new RuntimeSessionBusyError(request.session_id);

    const provider = this.options.providers.require(request.provider);
    const existing = this.options.sessions.get(request.session_id);
    if (existing && existing.provider !== provider.id) {
      throw new Error(`Runtime session ${request.session_id} belongs to provider ${existing.provider}`);
    }

    const abortController = new AbortController();
    const abort = () => abortController.abort(externalSignal?.reason);
    if (externalSignal?.aborted) abort();
    else externalSignal?.addEventListener("abort", abort, { once: true });
    this.active.set(request.session_id, abortController);

    const providerRequest: ProviderStartRequest = {
      ...request,
      ...(existing ? { native_session_id: existing.native_session_id } : {}),
    };
    const sink = this.options.eventSinkFactory(request);
    const executionId = this.uuid();
    let nativeSessionId = existing?.native_session_id;
    let accepted = false;
    let resolveAccepted!: (response: RuntimeStartResponse) => void;
    let rejectAccepted!: (error: unknown) => void;
    const acceptedResponse = new Promise<RuntimeStartResponse>((resolve, reject) => {
      resolveAccepted = resolve;
      rejectAccepted = reject;
    });

    const publishSource = async (sourceEvent: RuntimeEventEnvelope): Promise<number> => {
      const eventNativeSessionId = readNativeSessionId(sourceEvent);
      if (eventNativeSessionId) {
        if (nativeSessionId && nativeSessionId !== eventNativeSessionId) {
          throw new Error(`Provider changed native session id for ${request.session_id}`);
        }
        nativeSessionId = eventNativeSessionId;
      }
      if (!nativeSessionId) {
        throw new Error("Provider must identify native_session_id before publishing events");
      }
      if (!this.options.sessions.get(request.session_id)) {
        await this.options.sessions.upsert({
          session_id: request.session_id,
          provider: provider.id,
          native_session_id: nativeSessionId,
          sequence: 0,
        });
      }

      const current = this.options.sessions.require(request.session_id);
      const sequence = current.sequence + 1;
      const event: RuntimeEventEnvelope = {
        ...sourceEvent,
        session_id: request.session_id,
        turn_id: request.turn_id,
        sequence,
      };
      await sink.publish(event);
      await this.options.sessions.upsert({ ...current, sequence });
      return sequence;
    };

    const work = (async () => {
      try {
        for await (const sourceEvent of provider.start(providerRequest, abortController.signal)) {
          const acceptedSequence = await publishSource(sourceEvent);
          if (!accepted) {
            accepted = true;
            resolveAccepted({
              execution_id: executionId,
              native_session_id: nativeSessionId!,
              accepted_sequence: acceptedSequence,
            });
          }
        }
        if (!nativeSessionId) throw new Error("Provider completed without a native_session_id");
        if (!accepted) throw new Error("Provider completed without publishing an event");
      } catch (error) {
        if (!accepted) {
          rejectAccepted(error);
        } else if (!abortController.signal.aborted) {
          try {
            const detail = error instanceof Error ? error.message : "Unknown provider failure";
            await publishSource({
              event_id: this.uuid(),
              session_id: request.session_id,
              turn_id: request.turn_id,
              sequence: 0,
              event_type: "error",
              timestamp: new Date().toISOString(),
              payload: { code: "provider_execution_failed", message: detail },
              idempotency_key: `${request.idempotency_key}:provider-error`,
            });
            await publishSource({
              event_id: this.uuid(),
              session_id: request.session_id,
              turn_id: request.turn_id,
              sequence: 0,
              event_type: "session_state",
              timestamp: new Date().toISOString(),
              payload: { state: "failed", native_session_id: nativeSessionId },
              idempotency_key: `${request.idempotency_key}:provider-failed`,
            });
          } catch (reportingError) {
            const detail = reportingError instanceof Error ? reportingError.message : String(reportingError);
            console.error(`[agent-runtime] failed to publish provider failure: ${detail}`);
          }
        }
      } finally {
        this.active.delete(request.session_id);
        externalSignal?.removeEventListener("abort", abort);
      }
    })();
    this.background.set(request.session_id, work);
    void work.finally(() => {
      if (this.background.get(request.session_id) === work) this.background.delete(request.session_id);
    });

    return acceptedResponse;
  }

  async waitForIdle(sessionId: string): Promise<void> {
    await this.background.get(sessionId);
  }

  getSession(sessionId: string) {
    return this.options.sessions.get(sessionId);
  }

  async diagnostics(): Promise<Record<string, unknown>> {
    const providerStatuses = await Promise.all(this.options.providers.list().map(async entry => {
      if (!entry.enabled) return { id: entry.id, enabled: false, status: "unavailable" as const };
      try {
        return { id: entry.id, enabled: true, ...(await this.options.providers.require(entry.id).health()) };
      } catch (error) {
        return {
          id: entry.id,
          enabled: true,
          status: "unavailable" as const,
          detail: error instanceof Error ? error.message : String(error),
        };
      }
    }));
    return {
      status: providerStatuses.some(provider => provider.status === "unavailable") ? "degraded" : "ok",
      active_sessions: this.active.size,
      persisted_sessions: this.options.sessions.list().length,
      providers: providerStatuses,
    };
  }

  resume(request: RuntimeStartRequest, signal?: AbortSignal): Promise<RuntimeStartResponse> {
    return this.startTurn(request, signal);
  }

  async stop(sessionId: string): Promise<void> {
    const session = this.options.sessions.require(sessionId);
    this.active.get(sessionId)?.abort(new Error("Runtime session stopped"));
    await this.options.providers.require(session.provider).stop(sessionId);
  }

  async rewind(sessionId: string, checkpointId: string): Promise<void> {
    const session = this.options.sessions.require(sessionId);
    await this.options.providers.require(session.provider).rewind(sessionId, checkpointId);
  }

  async fork(
    sessionId: string,
    checkpointId: string,
    forkSessionId: string,
  ): Promise<{ session_id: string; native_session_id: string }> {
    if (this.options.sessions.get(forkSessionId)) {
      throw new Error(`Runtime session ${forkSessionId} already exists`);
    }
    const source = this.options.sessions.require(sessionId);
    const result = await this.options.providers.require(source.provider).fork(sessionId, checkpointId);
    await this.options.sessions.upsert({
      session_id: forkSessionId,
      provider: source.provider,
      native_session_id: result.native_session_id,
      sequence: 0,
    });
    return { session_id: forkSessionId, native_session_id: result.native_session_id };
  }
}

function readNativeSessionId(event: RuntimeEventEnvelope): string | undefined {
  const value = event.payload.native_session_id;
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
