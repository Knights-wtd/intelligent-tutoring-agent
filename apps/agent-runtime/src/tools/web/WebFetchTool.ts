import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { brotliDecompressSync, gunzipSync, inflateSync } from "node:zlib";

import { SsrfGuard, type ResolvedPublicUrl } from "../../security/ssrf";
import type { SidecarDescriptor, SidecarStore } from "../../runtime/SidecarStore";

export interface WebTransportRequest extends ResolvedPublicUrl { signal?: AbortSignal; maxResponseBytes: number; }
export interface WebTransportResponse { status: number; headers: Readonly<Record<string, string>>; body: Buffer; }
export type WebTransport = (request: WebTransportRequest) => Promise<WebTransportResponse>;
export interface WebFetchResult { url: string; status: number; mediaType: string; body?: Buffer; sidecar?: SidecarDescriptor; }
export interface WebFetchOptions {
  guard?: SsrfGuard;
  transport?: WebTransport;
  maxResponseBytes?: number;
  inlineBytes?: number;
  timeoutMs?: number;
  concurrency?: number;
  maxRedirects?: number;
  sidecarStore?: SidecarStore;
}

export class WebFetchTool {
  private readonly guard: SsrfGuard;
  private readonly transport: WebTransport;
  private readonly semaphore: Semaphore;
  private readonly maxResponseBytes: number;
  private readonly inlineBytes: number;
  private readonly timeoutMs: number;
  private readonly maxRedirects: number;

  constructor(private readonly options: WebFetchOptions = {}) {
    this.guard = options.guard ?? new SsrfGuard();
    this.transport = options.transport ?? nodeTransport;
    this.maxResponseBytes = options.maxResponseBytes ?? 10 * 1024 * 1024;
    this.inlineBytes = options.inlineBytes ?? 256 * 1024;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.maxRedirects = options.maxRedirects ?? 10;
    this.semaphore = new Semaphore(options.concurrency ?? 8);
  }

  async fetch(value: string, signal?: AbortSignal): Promise<WebFetchResult> {
    const release = await this.semaphore.acquire(signal);
    try { return await this.fetchHop(value, 0, signal); } finally { release(); }
  }

  private async fetchHop(value: string, redirectCount: number, parentSignal?: AbortSignal): Promise<WebFetchResult> {
    if (redirectCount > this.maxRedirects) throw new Error("Too many redirects");
    const resolved = await this.guard.resolve(value);
    const timeoutSignal = AbortSignal.timeout(this.timeoutMs);
    const signal = parentSignal ? AbortSignal.any([parentSignal, timeoutSignal]) : timeoutSignal;
    const response = await this.transport({ ...resolved, signal, maxResponseBytes: this.maxResponseBytes });
    if (response.status >= 300 && response.status < 400 && response.headers.location) {
      return this.fetchHop(new URL(response.headers.location, resolved.url).toString(), redirectCount + 1, parentSignal);
    }
    const body = decodeBody(response.body, response.headers["content-encoding"]);
    if (body.byteLength > this.maxResponseBytes) throw new Error("Web response exceeds decompressed size limit");
    const mediaType = (response.headers["content-type"] ?? "application/octet-stream").split(";", 1)[0].trim().toLowerCase();
    if (body.byteLength > this.inlineBytes) {
      if (!this.options.sidecarStore) throw new Error("Large web response requires a SidecarStore");
      const descriptor = await this.options.sidecarStore.putJson("web", createStableEventId(resolved.url.toString()), { url: resolved.url.toString(), media_type: mediaType, body_base64: body.toString("base64") });
      return { url: resolved.url.toString(), status: response.status, mediaType, sidecar: descriptor };
    }
    return { url: resolved.url.toString(), status: response.status, mediaType, body };
  }
}

async function nodeTransport(input: WebTransportRequest): Promise<WebTransportResponse> {
  const address = input.addresses[0];
  const request = input.url.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, reject) => {
    const req = request(input.url, {
      method: "GET",
      headers: { accept: "text/html,application/json,text/plain,*/*;q=0.1", "accept-encoding": "gzip, deflate, br", "user-agent": "Textbook-Agent-Runtime/1.0" },
      lookup: (_hostname, _options, callback) => callback(null, address, address.includes(":") ? 6 : 4),
      signal: input.signal,
      servername: input.url.hostname,
    }, response => {
      const chunks: Buffer[] = [];
      let size = 0;
      response.on("data", (chunk: Buffer) => {
        size += chunk.byteLength;
        if (size > input.maxResponseBytes) response.destroy(new Error("Web response exceeds compressed size limit"));
        else chunks.push(Buffer.from(chunk));
      });
      response.on("end", () => resolve({
        status: response.statusCode ?? 0,
        headers: Object.fromEntries(Object.entries(response.headers).flatMap(([key, value]) => value === undefined ? [] : [[key.toLowerCase(), Array.isArray(value) ? value.join(", ") : value]])),
        body: Buffer.concat(chunks),
      }));
      response.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

function decodeBody(body: Buffer, encoding?: string): Buffer {
  switch (encoding?.toLowerCase()) {
    case "gzip": return gunzipSync(body);
    case "deflate": return inflateSync(body);
    case "br": return brotliDecompressSync(body);
    default: return body;
  }
}
function createStableEventId(value: string): string { return Buffer.from(value).toString("base64url").slice(0, 96) || "response"; }

class Semaphore {
  private active = 0;
  private readonly waiters: Array<() => void> = [];
  constructor(private readonly limit: number) { if (!Number.isSafeInteger(limit) || limit < 1) throw new TypeError("concurrency must be positive"); }
  async acquire(signal?: AbortSignal): Promise<() => void> {
    if (this.active >= this.limit) await new Promise<void>((resolve, reject) => {
      const onAbort = () => reject(signal?.reason ?? new Error("Aborted"));
      signal?.addEventListener("abort", onAbort, { once: true });
      this.waiters.push(() => { signal?.removeEventListener("abort", onAbort); resolve(); });
    });
    signal?.throwIfAborted(); this.active += 1;
    return () => { this.active -= 1; this.waiters.shift()?.(); };
  }
}
