import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";

import type { SidecarDescriptor, SidecarStore } from "../../runtime/SidecarStore";
import type { PathPolicy } from "../../security/path-policy";
import { redactEnvironment } from "../../security/redact";
import { killProcessTree } from "./process-tree";

export interface BashAuditEvent {
  command: string;
  cwd: string;
  exitCode: number | null;
  durationMs: number;
  environment: Record<string, string>;
  stdoutBytes: number;
  stderrBytes: number;
  sidecar?: SidecarDescriptor;
}
export interface BashRunRequest { command: string; cwd: string; environment?: Readonly<Record<string, string | undefined>>; signal?: AbortSignal; }
export interface BashRunResult { exitCode: number | null; stdout: string; stderr: string; sidecar?: SidecarDescriptor; durationMs: number; }
export interface BashToolOptions { pathPolicy: PathPolicy; sidecarStore?: SidecarStore; inlineBytes?: number; onAudit?: (event: BashAuditEvent) => void; }

export class BashTool {
  constructor(private readonly options: BashToolOptions) {}

  async run(request: BashRunRequest): Promise<BashRunResult> {
    if (!request.command.trim()) throw new TypeError("command is required");
    const cwd = await this.options.pathPolicy.resolveReadable(request.cwd);
    const started = Date.now();
    const environment = { ...process.env, ...request.environment };
    const child = spawn(request.command, {
      cwd,
      env: environment,
      shell: true,
      windowsHide: true,
      detached: process.platform !== "win32",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout: Buffer[] = []; const stderr: Buffer[] = [];
    child.stdout.on("data", chunk => stdout.push(Buffer.from(chunk)));
    child.stderr.on("data", chunk => stderr.push(Buffer.from(chunk)));
    const onAbort = () => { if (child.pid) void killProcessTree(child.pid); };
    request.signal?.addEventListener("abort", onAbort, { once: true });
    const exitCode = await new Promise<number | null>((resolve, reject) => { child.once("error", reject); child.once("exit", code => resolve(code)); });
    request.signal?.removeEventListener("abort", onAbort);
    const stdoutBuffer = Buffer.concat(stdout); const stderrBuffer = Buffer.concat(stderr);
    const durationMs = Date.now() - started;
    let sidecar: SidecarDescriptor | undefined;
    const inlineBytes = this.options.inlineBytes ?? 256 * 1024;
    if (stdoutBuffer.byteLength + stderrBuffer.byteLength > inlineBytes) {
      if (!this.options.sidecarStore) throw new Error("Large command output requires a SidecarStore");
      sidecar = await this.options.sidecarStore.putJson("shell", randomUUID(), { command: request.command, cwd, exit_code: exitCode, stdout: stdoutBuffer.toString("utf8"), stderr: stderrBuffer.toString("utf8") });
    }
    this.options.onAudit?.({
      command: request.command,
      cwd,
      exitCode,
      durationMs,
      environment: redactEnvironment(request.environment ?? {}),
      stdoutBytes: stdoutBuffer.byteLength,
      stderrBytes: stderrBuffer.byteLength,
      ...(sidecar ? { sidecar } : {}),
    });
    return { exitCode, stdout: sidecar ? "" : stdoutBuffer.toString("utf8"), stderr: sidecar ? "" : stderrBuffer.toString("utf8"), ...(sidecar ? { sidecar } : {}), durationMs };
  }
}
