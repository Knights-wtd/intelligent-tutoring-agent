import { watch, type FSWatcher } from "node:fs";
import type { SkillRepository } from "./SkillRepository";

export class SkillWatcher {
  private readonly watchers: FSWatcher[] = [];
  private timer?: NodeJS.Timeout;
  constructor(private readonly repository: SkillRepository, private readonly roots: readonly string[], private readonly debounceMs = 100) {}
  start(): void {
    for (const root of this.roots) {
      try { this.watchers.push(watch(root, { recursive: true }, () => this.scheduleRefresh())); } catch {}
    }
  }
  close(): void { for (const watcher of this.watchers.splice(0)) watcher.close(); if (this.timer) clearTimeout(this.timer); }
  private scheduleRefresh(): void { if (this.timer) clearTimeout(this.timer); this.timer = setTimeout(() => { void this.repository.refresh(); }, this.debounceMs); }
}
