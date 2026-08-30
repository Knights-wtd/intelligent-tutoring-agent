import { createHash } from "node:crypto";
import { lstat, mkdir, opendir, readFile, rename, rm } from "node:fs/promises";
import { extname, relative, sep } from "node:path";

import { PathPolicy } from "../security/path-policy";
import { atomicWriteFile } from "./atomic-write";
import { VaultChangePublisher, type VaultChangeEvent } from "./watcher";

export interface HostVaultAdapter {
  read(relativePath: string): Promise<Buffer>;
  writeAtomic(relativePath: string, content: Buffer, expectedHash?: string): Promise<{ beforeHash: string | null; afterHash: string }>;
  moveAtomic(from: string, to: string, expectedHash?: string): Promise<void>;
  remove(relativePath: string, expectedHash?: string): Promise<void>;
  list(prefix?: string): AsyncIterable<{ path: string; size: number; sha256: string }>;
}

export class VaultConflictError extends Error {
  readonly code = "vault_conflict" as const;
  constructor(message = "Vault content changed since it was read") { super(message); this.name = "VaultConflictError"; }
}

export class VaultFileTypeError extends Error {
  readonly code = "vault_file_type_denied" as const;
  constructor(path: string) { super(`Vault file type is not allowed: ${path}`); this.name = "VaultFileTypeError"; }
}

export interface LocalHostVaultOptions { allowedExtensions?: readonly string[]; }

export class LocalHostVaultAdapter implements HostVaultAdapter {
  private readonly changes = new VaultChangePublisher();
  private readonly allowedExtensions: Set<string>;

  private constructor(private readonly root: string, private readonly policy: PathPolicy, options: LocalHostVaultOptions) {
    this.allowedExtensions = new Set((options.allowedExtensions ?? [".md"]).map(value => value.toLowerCase()));
  }

  static async create(root: string, options: LocalHostVaultOptions = {}): Promise<LocalHostVaultAdapter> {
    await mkdir(root, { recursive: true });
    const policy = await PathPolicy.create([root]);
    const canonicalRoot = await policy.resolveReadable(".");
    return new LocalHostVaultAdapter(canonicalRoot, policy, options);
  }

  onChange(listener: (event: VaultChangeEvent) => void): () => void { return this.changes.onChange(listener); }

  async read(relativePath: string): Promise<Buffer> {
    this.requireAllowedType(relativePath);
    return readFile(await this.policy.resolveReadable(relativePath));
  }

  async writeAtomic(relativePath: string, content: Buffer, expectedHash?: string): Promise<{ beforeHash: string | null; afterHash: string }> {
    this.requireAllowedType(relativePath);
    const target = await this.policy.resolveWritable(relativePath);
    const beforeHash = await hashIfFile(target);
    requireExpectedHash(beforeHash, expectedHash);
    await atomicWriteFile(target, content);
    const afterHash = sha256(content);
    this.changes.publish({ type: beforeHash === null ? "created" : "modified", path: normalizeRelative(this.root, target), beforeHash, afterHash });
    return { beforeHash, afterHash };
  }

  async moveAtomic(from: string, to: string, expectedHash?: string): Promise<void> {
    this.requireAllowedType(from); this.requireAllowedType(to);
    const source = await this.policy.resolveReadable(from);
    const target = await this.policy.resolveWritable(to);
    const beforeHash = await hashIfFile(source);
    requireExpectedHash(beforeHash, expectedHash);
    if (await exists(target)) throw new VaultConflictError("Vault move target already exists");
    await mkdir(target.slice(0, Math.max(target.lastIndexOf("/"), target.lastIndexOf("\\"))), { recursive: true });
    await rename(source, target);
    this.changes.publish({ type: "moved", path: normalizeRelative(this.root, target), from: normalizeRelative(this.root, source), beforeHash, afterHash: beforeHash });
  }

  async remove(relativePath: string, expectedHash?: string): Promise<void> {
    this.requireAllowedType(relativePath);
    const target = await this.policy.resolveReadable(relativePath);
    const beforeHash = await hashIfFile(target);
    requireExpectedHash(beforeHash, expectedHash);
    await rm(target);
    this.changes.publish({ type: "removed", path: normalizeRelative(this.root, target), beforeHash, afterHash: null });
  }

  async *list(prefix = "."): AsyncIterable<{ path: string; size: number; sha256: string }> {
    let start: string;
    try { start = await this.policy.resolveReadable(prefix); } catch (error) {
      if (error instanceof Error && error.message.includes("does not exist")) return;
      throw error;
    }
    const records: Array<{ path: string; size: number; sha256: string }> = [];
    await this.collect(start, records);
    records.sort((left, right) => left.path.localeCompare(right.path));
    for (const record of records) yield record;
  }

  private async collect(path: string, records: Array<{ path: string; size: number; sha256: string }>): Promise<void> {
    const stat = await lstat(path);
    if (stat.isSymbolicLink()) return;
    if (stat.isFile()) {
      const relativePath = normalizeRelative(this.root, path);
      if (!this.allowedExtensions.has(extname(relativePath).toLowerCase())) return;
      const content = await readFile(path);
      records.push({ path: relativePath, size: content.byteLength, sha256: sha256(content) });
      return;
    }
    if (!stat.isDirectory()) return;
    const directory = await opendir(path);
    for await (const entry of directory) await this.collect(await this.policy.resolveReadable(normalizeRelative(this.root, path + sep + entry.name)), records);
  }

  private requireAllowedType(path: string): void {
    if (!this.allowedExtensions.has(extname(path).toLowerCase())) throw new VaultFileTypeError(path);
  }
}

function requireExpectedHash(actual: string | null, expected?: string): void {
  if (expected !== undefined && actual !== expected) throw new VaultConflictError();
}
function sha256(content: Buffer): string { return createHash("sha256").update(content).digest("hex"); }
async function hashIfFile(path: string): Promise<string | null> { try { return sha256(await readFile(path)); } catch (error) { if (isMissing(error)) return null; throw error; } }
async function exists(path: string): Promise<boolean> { try { await lstat(path); return true; } catch (error) { if (isMissing(error)) return false; throw error; } }
function isMissing(error: unknown): boolean { return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT"; }
function normalizeRelative(root: string, path: string): string { return relative(root, path).split(sep).join("/"); }
