import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

export class SsrfBlockedError extends Error {
  readonly code = "ssrf_blocked" as const;
  constructor(message = "Target is not a public HTTP(S) address") { super(message); this.name = "SsrfBlockedError"; }
}

export type HostResolver = (hostname: string) => Promise<readonly string[]>;

export interface ResolvedPublicUrl { url: URL; addresses: readonly string[]; }

export class SsrfGuard {
  constructor(private readonly resolver: HostResolver = resolveHost) {}

  async resolve(value: string | URL): Promise<ResolvedPublicUrl> {
    let url: URL;
    try { url = value instanceof URL ? new URL(value) : new URL(value); } catch { throw new SsrfBlockedError("Invalid URL"); }
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new SsrfBlockedError("Only HTTP and HTTPS are allowed");
    if (url.username || url.password) throw new SsrfBlockedError("URL credentials are not allowed");
    const hostname = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (!hostname || hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local")) throw new SsrfBlockedError();
    const addresses = isIP(hostname) ? [hostname] : [...await this.resolver(hostname)];
    if (addresses.length === 0 || addresses.some(address => !isPublicAddress(address))) throw new SsrfBlockedError();
    return { url, addresses };
  }
}

async function resolveHost(hostname: string): Promise<readonly string[]> {
  return (await lookup(hostname, { all: true, verbatim: true })).map(item => item.address);
}

export function isPublicAddress(address: string): boolean {
  const version = isIP(address);
  if (version === 4) return isPublicIpv4(address);
  if (version === 6) return isPublicIpv6(address);
  return false;
}

function isPublicIpv4(address: string): boolean {
  const parts = address.split(".").map(Number);
  if (parts.length !== 4 || parts.some(part => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  const [a, b, c] = parts;
  if (a === 0 || a === 10 || a === 127 || a >= 224) return false;
  if (a === 100 && b >= 64 && b <= 127) return false;
  if (a === 169 && b === 254) return false;
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 192 && b === 168) return false;
  if (a === 192 && b === 0 && (c === 0 || c === 2)) return false;
  if (a === 198 && (b === 18 || b === 19)) return false;
  if (a === 198 && b === 51 && c === 100) return false;
  if (a === 203 && b === 0 && c === 113) return false;
  return true;
}

function isPublicIpv6(address: string): boolean {
  const normalized = address.toLowerCase();
  if (normalized === "::" || normalized === "::1") return false;
  if (normalized.startsWith("fc") || normalized.startsWith("fd") || /^fe[89ab]/.test(normalized) || normalized.startsWith("ff")) return false;
  if (normalized.startsWith("2001:db8:")) return false;
  const mapped = normalized.match(/::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  return mapped ? isPublicIpv4(mapped[1]) : true;
}
