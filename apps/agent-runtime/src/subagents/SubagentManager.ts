import { randomUUID } from "node:crypto";

export interface SubagentRequest { parentSessionId: string; parentToolCallId: string; prompt: string; signal?: AbortSignal; }
export interface SubagentOutput { text: string; [key: string]: unknown; }
export interface SubagentResult extends SubagentOutput { subagentId: string; parentSessionId: string; parentToolCallId: string; }
export interface SubagentEvent { type: "started" | "completed" | "failed"; subagentId: string; parentSessionId: string; parentToolCallId: string; error?: string; }
export interface SubagentManagerOptions { concurrency: number; run: (request: SubagentRequest & { subagentId: string }) => Promise<SubagentOutput>; onEvent?: (event: SubagentEvent) => void; }

export class SubagentManager {
  private active = 0; private queued = 0; private completed = 0; private failed = 0;
  private readonly waiters: Array<() => void> = [];
  constructor(private readonly options: SubagentManagerOptions) { if (!Number.isSafeInteger(options.concurrency) || options.concurrency < 1) throw new TypeError("subagent concurrency must be positive"); }

  async run(request: SubagentRequest): Promise<SubagentResult> {
    const release = await this.acquire(request.signal); const subagentId = randomUUID();
    this.options.onEvent?.({ type: "started", subagentId, parentSessionId: request.parentSessionId, parentToolCallId: request.parentToolCallId });
    try {
      const output = await this.options.run({ ...request, subagentId }); this.completed += 1;
      this.options.onEvent?.({ type: "completed", subagentId, parentSessionId: request.parentSessionId, parentToolCallId: request.parentToolCallId });
      return { ...output, subagentId, parentSessionId: request.parentSessionId, parentToolCallId: request.parentToolCallId };
    } catch (error) {
      this.failed += 1; this.options.onEvent?.({ type: "failed", subagentId, parentSessionId: request.parentSessionId, parentToolCallId: request.parentToolCallId, error: error instanceof Error ? error.message : String(error) }); throw error;
    } finally { release(); }
  }

  diagnostics(): { active: number; queued: number; completed: number; failed: number; concurrency: number } { return { active: this.active, queued: this.queued, completed: this.completed, failed: this.failed, concurrency: this.options.concurrency }; }

  private async acquire(signal?: AbortSignal): Promise<() => void> {
    if (this.active >= this.options.concurrency) {
      this.queued += 1;
      try { await new Promise<void>((resolve, reject) => { const abort = () => reject(signal?.reason ?? new Error("Aborted")); signal?.addEventListener("abort", abort, { once: true }); this.waiters.push(() => { signal?.removeEventListener("abort", abort); resolve(); }); }); }
      finally { this.queued -= 1; }
    }
    signal?.throwIfAborted(); this.active += 1;
    return () => { this.active -= 1; this.waiters.shift()?.(); };
  }
}
