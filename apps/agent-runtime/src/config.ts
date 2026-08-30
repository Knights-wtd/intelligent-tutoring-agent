export interface RuntimeConfig {
  host: "127.0.0.1" | "::1";
  port: number;
  apiToken: string;
  sidecarRoot: string;
  vaultRoot?: string;
  claudeExecutable?: string;
  faroApiBaseUrl: string;
  faroApiKey: string;
  faroProxyUrl?: string;
  faroModel: string;
  faroTimeoutSeconds: number;
  maxContextTokens: number;
  sessionStatePath: string;
  capabilitySecret: string;
  inlineEventBytes: number;
}

export type RuntimeEnvironment = Readonly<Record<string, string | undefined>>;

export function assertSupportedNodeVersion(nodeVersion: string): void {
  const major = Number.parseInt(nodeVersion.split(".", 1)[0] ?? "", 10);
  if (major !== 24) {
    throw new Error(`Agent Runtime requires Node.js 24; received ${nodeVersion}`);
  }
}

export function loadRuntimeConfig(
  environment: RuntimeEnvironment = process.env,
  nodeVersion = process.versions.node,
): RuntimeConfig {
  assertSupportedNodeVersion(nodeVersion);

  const host = environment.AGENT_RUNTIME_HOST ?? "127.0.0.1";
  if (host !== "127.0.0.1" && host !== "::1") {
    throw new Error("AGENT_RUNTIME_HOST must be a loopback address");
  }

  const port = parseInteger(environment.AGENT_RUNTIME_PORT ?? "8765", "AGENT_RUNTIME_PORT", 0, 65_535);
  const apiToken = requireValue(environment.AGENT_RUNTIME_TOKEN, "AGENT_RUNTIME_TOKEN");
  const sidecarRoot = requireValue(
    environment.AGENT_RUNTIME_SIDECAR_ROOT,
    "AGENT_RUNTIME_SIDECAR_ROOT",
  );
  const vaultRoot = environment.AGENT_RUNTIME_VAULT_ROOT?.trim() || undefined;
  const claudeExecutable = environment.AGENT_RUNTIME_CLAUDE_EXECUTABLE?.trim() || undefined;
  const faroApiBaseUrl = (environment.AGENT_RUNTIME_FARO_API_BASE_URL
    ?? environment.FARO_API_BASE_URL
    ?? "https://faroapi.com/v1").trim().replace(/\/$/, "");
  const faroApiKey = (environment.AGENT_RUNTIME_FARO_API_KEY
    ?? environment.FARO_API_KEY
    ?? "").trim();
  const faroProxyUrl = optionalHttpProxyUrl(
    environment.AGENT_RUNTIME_FARO_PROXY_URL ?? environment.FARO_PROXY_URL,
    "AGENT_RUNTIME_FARO_PROXY_URL",
  );
  const faroModel = (environment.AGENT_RUNTIME_FARO_MODEL
    ?? environment.FARO_MODEL
    ?? "gemini-3.7-flash-tiered").trim();
  const faroTimeoutSeconds = parseInteger(
    environment.AGENT_RUNTIME_FARO_TIMEOUT_SECONDS
      ?? environment.FARO_TIMEOUT_SECONDS
      ?? "60",
    "AGENT_RUNTIME_FARO_TIMEOUT_SECONDS",
    1,
    600,
  );
  const maxContextTokens = parseInteger(
    environment.AGENT_RUNTIME_MAX_CONTEXT_TOKENS ?? "1000000",
    "AGENT_RUNTIME_MAX_CONTEXT_TOKENS",
    1,
    Number.MAX_SAFE_INTEGER,
  );

  const sessionStatePath = environment.AGENT_RUNTIME_SESSION_STATE
    ?? `${sidecarRoot.replace(/[\\/]+$/, "")}/sessions.json`;
  const capabilitySecret = environment.AGENT_RUNTIME_CAPABILITY_SECRET ?? apiToken;
  const inlineEventBytes = parseInteger(
    environment.AGENT_RUNTIME_INLINE_EVENT_BYTES ?? "262144",
    "AGENT_RUNTIME_INLINE_EVENT_BYTES",
    1,
    Number.MAX_SAFE_INTEGER,
  );

  return {
    host,
    port,
    apiToken,
    sidecarRoot,
    ...(vaultRoot ? { vaultRoot } : {}),
    ...(claudeExecutable ? { claudeExecutable } : {}),
    faroApiBaseUrl,
    faroApiKey,
    ...(faroProxyUrl ? { faroProxyUrl } : {}),
    faroModel: requireValue(faroModel, "AGENT_RUNTIME_FARO_MODEL"),
    faroTimeoutSeconds,
    maxContextTokens,
    sessionStatePath,
    capabilitySecret,
    inlineEventBytes,
  };
}

function optionalHttpProxyUrl(value: string | undefined, name: string): string | undefined {
  const normalized = value?.trim();
  if (!normalized) return undefined;

  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error(`${name} must be an absolute http:// proxy URL`);
  }
  if (parsed.protocol !== "http:" || !parsed.hostname || parsed.search || parsed.hash) {
    throw new Error(`${name} must be an absolute http:// proxy URL`);
  }
  return normalized;
}

function requireValue(value: string | undefined, name: string): string {
  if (!value || value.trim().length === 0) throw new Error(`${name} is required`);
  return value;
}

function parseInteger(value: string, name: string, minimum: number, maximum: number): number {
  if (!/^\d+$/.test(value)) throw new Error(`${name} must be an integer`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be between ${minimum} and ${maximum}`);
  }
  return parsed;
}


