import { randomUUID } from "node:crypto";
import { mkdir, open, rename } from "node:fs/promises";
import { dirname } from "node:path";

export async function atomicWriteFile(target: string, content: Buffer, retries = 5): Promise<void> {
  await mkdir(dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  const handle = await open(temporary, "wx");
  try { await handle.writeFile(content); await handle.sync(); } finally { await handle.close(); }
  for (let attempt = 0; ; attempt += 1) {
    try { await rename(temporary, target); return; }
    catch (error) {
      if (attempt >= retries || !isRetryableRename(error)) throw error;
      await new Promise(resolve => setTimeout(resolve, 10 * 2 ** attempt));
    }
  }
}

function isRetryableRename(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && ["EACCES", "EBUSY", "EPERM"].includes(String(error.code));
}
