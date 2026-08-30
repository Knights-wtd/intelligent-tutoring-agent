import { spawn } from "node:child_process";

export async function killProcessTree(pid: number): Promise<void> {
  if (!Number.isSafeInteger(pid) || pid < 1) return;
  if (process.platform === "win32") {
    await new Promise<void>(resolve => {
      const child = spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
      child.once("exit", () => resolve()); child.once("error", () => resolve());
    });
    return;
  }
  try { process.kill(-pid, "SIGTERM"); } catch { try { process.kill(pid, "SIGTERM"); } catch {} }
}
