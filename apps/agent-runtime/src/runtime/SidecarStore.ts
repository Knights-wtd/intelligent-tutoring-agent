import { createHash, randomUUID } from "node:crypto";
import { link, mkdir, readFile, stat, unlink, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";

export interface SidecarDescriptor {
  sidecar_id: string;
  sha256: string;
  size: number;
  media_type: string;
}

export class SidecarStore {
  private readonly resolvedRoot: string;

  constructor(readonly root: string) {
    this.resolvedRoot = resolve(root);
  }

  async putJson(sessionId: string, eventId: string, payload: Record<string, unknown>): Promise<SidecarDescriptor> {
    assertSafeSegment(sessionId, "sessionId");
    assertSafeSegment(eventId, "eventId");
    const bytes = Buffer.from(JSON.stringify(payload), "utf8");
    const sidecarId = `${sessionId}/${eventId}.json`;
    const target = this.pathFor(sidecarId);
    await mkdir(dirname(target), { recursive: true });
    const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(temporary, bytes, { flag: "wx" });
    try {
      // Publishing with a hard link is atomic and never overwrites an existing
      // event sidecar. Replays may reuse the path only when bytes are identical.
      await link(temporary, target);
    } catch (error) {
      if (!isAlreadyExists(error)) throw error;
      const existing = await readFile(target);
      if (!existing.equals(bytes)) {
        throw new Error(`sidecar ${sidecarId} already exists with different content`);
      }
    } finally {
      await unlink(temporary).catch(() => undefined);
    }
    return descriptor(sidecarId, bytes);
  }

  async read(
    sidecarId: string,
    range?: { start: number; end?: number },
  ): Promise<{ bytes: Buffer; totalSize: number; mediaType: string }> {
    const target = this.pathFor(sidecarId);
    const metadata = await stat(target);
    if (!metadata.isFile()) throw new Error("sidecar is not a regular file");
    const bytes = await readFile(target);
    const start = range?.start ?? 0;
    const end = Math.min(range?.end ?? bytes.byteLength - 1, bytes.byteLength - 1);
    if (start >= bytes.byteLength || end < start) {
      const error = new RangeError("sidecar byte range is unsatisfiable");
      Object.assign(error, { status: 416, code: "range_not_satisfiable" });
      throw error;
    }
    return {
      bytes: bytes.subarray(start, end + 1),
      totalSize: metadata.size,
      mediaType: sidecarId.endsWith(".json") ? "application/json" : "application/octet-stream",
    };
  }

  pathFor(sidecarId: string): string {
    const target = resolve(this.resolvedRoot, ...sidecarId.split("/"));
    const child = relative(this.resolvedRoot, target);
    if (!child || child.startsWith("..") || resolve(this.resolvedRoot, child) !== target) {
      throw new Error("sidecar path escapes the configured root");
    }
    return target;
  }
}

function descriptor(sidecarId: string, bytes: Buffer): SidecarDescriptor {
  return {
    sidecar_id: sidecarId,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    size: bytes.byteLength,
    media_type: "application/json",
  };
}

function assertSafeSegment(value: string, name: string): void {
  if (!/^[A-Za-z0-9._-]+$/.test(value) || value === "." || value === "..") {
    throw new TypeError(`${name} contains unsafe path characters`);
  }
}

function isAlreadyExists(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "EEXIST";
}
