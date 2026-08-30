import { posix, win32 } from "node:path";

const LOGICAL_VAULT_ROOT = "/agent-vault";

export type HostPathPlatform = "win32" | "posix";

export function mapWorkspaceRoots(
  roots: readonly string[],
  hostVaultRoot: string,
  platform: HostPathPlatform = process.platform === "win32" ? "win32" : "posix",
): string[] {
  if (!hostVaultRoot || hostVaultRoot.includes("\0")) {
    throw new TypeError("Managed host vault root is invalid");
  }
  const flavor = platform === "win32" ? win32 : posix;
  const managedRoot = flavor.resolve(hostVaultRoot);
  return roots.map(root => {
    if (!root || root.includes("\0")) throw outsideLogicalVault();
    const normalized = posix.normalize(root);
    if (normalized !== LOGICAL_VAULT_ROOT && !normalized.startsWith(`${LOGICAL_VAULT_ROOT}/`)) {
      throw outsideLogicalVault();
    }
    const relativeRoot = posix.relative(LOGICAL_VAULT_ROOT, normalized);
    if (relativeRoot.startsWith("..") || posix.isAbsolute(relativeRoot)) throw outsideLogicalVault();
    const target = flavor.resolve(managedRoot, ...relativeRoot.split("/").filter(Boolean));
    const relativeTarget = flavor.relative(managedRoot, target);
    if (relativeTarget.startsWith("..") || flavor.isAbsolute(relativeTarget)) {
      throw new TypeError("Mapped workspace root escapes the managed host vault");
    }
    return target;
  });
}

function outsideLogicalVault(): TypeError {
  return new TypeError("Workspace root is outside the logical vault");
}
