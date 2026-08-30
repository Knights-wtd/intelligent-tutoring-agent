import type { AgentProvider } from "./types";

export class ProviderUnavailableError extends Error {
  readonly code = "provider_unavailable" as const;

  constructor(readonly providerId: string, detail?: string) {
    super(detail ?? `Provider \"${providerId}\" is unavailable`);
    this.name = "ProviderUnavailableError";
  }
}

interface ProviderEntry {
  provider: AgentProvider;
  enabled: boolean;
}

export class ProviderRegistry {
  private readonly providers = new Map<string, ProviderEntry>();

  register(provider: AgentProvider, options: { enabled?: boolean } = {}): void {
    if (!provider.id.trim()) throw new TypeError("provider.id is required");
    if (this.providers.has(provider.id)) throw new Error(`Provider \"${provider.id}\" is already registered`);
    this.providers.set(provider.id, { provider, enabled: options.enabled ?? true });
  }

  setEnabled(providerId: string, enabled: boolean): void {
    const entry = this.providers.get(providerId);
    if (!entry) throw new ProviderUnavailableError(providerId);
    entry.enabled = enabled;
  }

  require(providerId: string): AgentProvider {
    const entry = this.providers.get(providerId);
    if (!entry?.enabled) throw new ProviderUnavailableError(providerId);
    return entry.provider;
  }

  list(): readonly { id: string; enabled: boolean }[] {
    return [...this.providers.entries()].map(([id, entry]) => ({ id, enabled: entry.enabled }));
  }
}
