export interface VaultChangeEvent {
  type: "created" | "modified" | "moved" | "removed";
  path: string;
  from?: string;
  beforeHash?: string | null;
  afterHash?: string | null;
}

export class VaultChangePublisher {
  private readonly listeners = new Set<(event: VaultChangeEvent) => void>();
  onChange(listener: (event: VaultChangeEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  publish(event: VaultChangeEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}
