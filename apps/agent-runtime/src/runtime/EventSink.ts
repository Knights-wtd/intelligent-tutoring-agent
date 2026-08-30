import type { RuntimeEventEnvelope } from "@textbook-agent/agent-protocol";

import type { SidecarStore } from "./SidecarStore";

export interface EventPostResult {
  ok: boolean;
  status: number;
  body: unknown;
}

export type EventPoster = (url: string, event: RuntimeEventEnvelope) => Promise<EventPostResult>;

export interface EventSinkOptions {
  callbackUrl: string;
  callbackToken?: string;
  post?: EventPoster;
  sleep?: (milliseconds: number) => Promise<void>;
  inlineEventBytes?: number;
  sidecarStore?: SidecarStore;
  signal?: AbortSignal;
}

const RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 30_000] as const;

export class EventSink {
  private readonly cursors = new Map<string, number>();
  private readonly acknowledged = new Set<string>();
  private readonly inFlight = new Map<string, Promise<void>>();
  private readonly post: EventPoster;
  private readonly sleep: (milliseconds: number) => Promise<void>;

  constructor(private readonly options: EventSinkOptions) {
    if (!options.callbackUrl) throw new TypeError("callbackUrl is required");
    if (!options.post && !options.callbackToken) {
      throw new TypeError("callbackToken is required when using the default event poster");
    }
    this.post = options.post ?? ((url, event) => postJson(url, event, options.callbackToken!));
    this.sleep = options.sleep ?? delay;
  }

  cursorFor(sessionId: string): number {
    return this.cursors.get(sessionId) ?? 0;
  }

  publish(source: RuntimeEventEnvelope): Promise<void> {
    if (this.acknowledged.has(source.idempotency_key)) return Promise.resolve();
    const existing = this.inFlight.get(source.idempotency_key);
    if (existing) return existing;
    const delivery = this.publishOnce(source).finally(() => {
      if (this.inFlight.get(source.idempotency_key) === delivery) {
        this.inFlight.delete(source.idempotency_key);
      }
    });
    this.inFlight.set(source.idempotency_key, delivery);
    return delivery;
  }

  private async publishOnce(source: RuntimeEventEnvelope): Promise<void> {
    const event = await this.externalizePayload(source);
    let attempt = 0;
    while (true) {
      this.options.signal?.throwIfAborted();
      let response: EventPostResult | undefined;
      try {
        response = await this.post(this.options.callbackUrl, event);
      } catch (error) {
        if (this.options.signal?.aborted) throw error;
      }
      if (response?.ok && isDurableAck(response.body, event.sequence)) {
        this.acknowledged.add(event.idempotency_key);
        this.cursors.set(event.session_id, Math.max(this.cursorFor(event.session_id), event.sequence));
        return;
      }
      const wait = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)];
      attempt += 1;
      await this.sleep(wait);
    }
  }

  private async externalizePayload(event: RuntimeEventEnvelope): Promise<RuntimeEventEnvelope> {
    const limit = this.options.inlineEventBytes;
    if (limit === undefined || Buffer.byteLength(JSON.stringify(event.payload), "utf8") <= limit) return event;
    if (!this.options.sidecarStore) throw new Error("Oversized event payload requires a SidecarStore");
    const descriptor = await this.options.sidecarStore.putJson(event.session_id, event.event_id, event.payload);
    return { ...event, payload: { ...descriptor } };
  }
}

function isDurableAck(value: unknown, sequence: number): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const body = value as Record<string, unknown>;
  return body.persisted === true
    && Number.isSafeInteger(body.accepted_sequence)
    && Number(body.accepted_sequence) >= sequence;
}

async function postJson(
  url: string,
  event: RuntimeEventEnvelope,
  callbackToken: string,
): Promise<EventPostResult> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "idempotency-key": event.idempotency_key,
      authorization: `Bearer ${callbackToken}`,
    },
    body: JSON.stringify(event),
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  return { ok: response.ok, status: response.status, body };
}

function delay(milliseconds: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}
