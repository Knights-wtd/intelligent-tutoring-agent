import { lstat, realpath } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep, win32, posix } from "node:path";

export class PathPolicyError extends Error {
  readonly code = "path_outside_grant" as const;
  constructor(message = "Path is outside granted roots") { super(message); this.name = "PathPolicyError"; }
}

export interface PathPolicyOptions { platform?: "win32" | "posix"; }

export class PathPolicy {
  private constructor(private readonly roots: readonly string[], private readonly platform: "win32" | "posix") {}

  static async create(roots: readonly string[], options: PathPolicyOptions = {}): Promise<PathPolicy> {
    if (roots.length === 0) throw new TypeError("At least one granted root is required");
    const canonical = await Promise.all(roots.map(async root => realpath(resolve(root))));
    return new PathPolicy(canonical, options.platform ?? (process.platform === "win32" ? "win32" : "posix"));
  }

  async resolveReadable(candidate: string): Promise<string> {
    const lexical = this.resolveLexical(candidate);
    let canonical: string;
    try { canonical = await realpath(lexical); } catch { throw new PathPolicyError("Readable path does not exist inside a granted root"); }
    this.requireContained(canonical);
    return canonical;
  }

  async resolveWritable(candidate: string): Promise<string> {
    const lexical = this.resolveLexical(candidate);
    const { ancestor, suffix } = await findExistingAncestor(lexical);
    let canonicalAncestor: string;
    try { canonicalAncestor = await realpath(ancestor); } catch { throw new PathPolicyError(); }
    this.requireContained(canonicalAncestor);
    const target = resolve(canonicalAncestor, ...suffix);
    this.requireContained(target);
    return target;
  }

  private resolveLexical(raw: string): string {
    if (typeof raw !== "string" || raw.length === 0 || raw.includes("\0")) throw new PathPolicyError();
    const candidate = raw.normalize("NFKC");
    if (/%(?:2e|2f|5c)/i.test(candidate)) throw new PathPolicyError("Encoded traversal is not allowed");
    if (this.platform === "win32" && /^[A-Za-z]:/.test(candidate) && !win32.isAbsolute(candidate)) throw new PathPolicyError("Drive-relative paths are not allowed");
    const flavor = this.platform === "win32" ? win32 : posix;
    const flavorAbsolute = flavor.isAbsolute(candidate);
    const nativeCandidate = this.platform === "win32" ? candidate.replace(/[\\/]+/g, sep) : candidate;
    const target = flavorAbsolute || isAbsolute(nativeCandidate)
      ? resolve(nativeCandidate)
      : resolve(this.roots[0], nativeCandidate);
    this.requireContained(target);
    return target;
  }

  private requireContained(target: string): void {
    if (!this.roots.some(root => contains(root, target, this.platform === "win32"))) throw new PathPolicyError();
  }
}

async function findExistingAncestor(target: string): Promise<{ ancestor: string; suffix: string[] }> {
  const suffix: string[] = [];
  let current = target;
  while (true) {
    try { await lstat(current); return { ancestor: current, suffix }; }
    catch (error) {
      if (!isMissing(error)) throw error;
      const parent = dirname(current);
      if (parent === current) throw new PathPolicyError();
      suffix.unshift(current.slice(parent.length).replace(/^[/\\]+/, ""));
      current = parent;
    }
  }
}

function contains(root: string, target: string, caseInsensitive: boolean): boolean {
  const normalizedRoot = caseInsensitive ? root.toLowerCase() : root;
  const normalizedTarget = caseInsensitive ? target.toLowerCase() : target;
  const child = relative(normalizedRoot, normalizedTarget);
  return child === "" || (!child.startsWith("..") && !isAbsolute(child));
}

function isMissing(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error.code === "ENOENT" || error.code === "ENOTDIR");
}
