import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { LocalHostVaultAdapter, VaultConflictError } from "../src/vault/HostVaultAdapter";

const sha256 = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

describe("LocalHostVaultAdapter", () => {
  it("performs authorized atomic CRUD and emits change events", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-vault-"));
    try {
      const vault = await LocalHostVaultAdapter.create(root, { allowedExtensions: [".md", ".txt"] });
      const changes: string[] = [];
      vault.onChange(change => changes.push(change.type));

      const first = await vault.writeAtomic("notes/a.md", Buffer.from("one"));
      expect(first).toEqual({ beforeHash: null, afterHash: sha256("one") });
      await expect(vault.read("notes/a.md")).resolves.toEqual(Buffer.from("one"));

      const second = await vault.writeAtomic("notes/a.md", Buffer.from("two"), first.afterHash);
      expect(second.beforeHash).toBe(first.afterHash);
      await vault.moveAtomic("notes/a.md", "notes/b.md", second.afterHash);
      const listed = [];
      for await (const item of vault.list("notes")) listed.push(item);
      expect(listed).toEqual([{ path: "notes/b.md", size: 3, sha256: sha256("two") }]);
      await vault.remove("notes/b.md", second.afterHash);
      expect(changes).toEqual(["created", "modified", "moved", "removed"]);
    } finally { await rm(root, { recursive: true, force: true }); }
  });

  it("does not overwrite on expected hash conflict or unsupported extension", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-vault-"));
    try {
      const vault = await LocalHostVaultAdapter.create(root);
      await vault.writeAtomic("a.md", Buffer.from("original"));
      await expect(vault.writeAtomic("a.md", Buffer.from("lost"), sha256("other"))).rejects.toBeInstanceOf(VaultConflictError);
      await expect(vault.read("a.md")).resolves.toEqual(Buffer.from("original"));
      await expect(vault.writeAtomic("run.exe", Buffer.from("x"))).rejects.toMatchObject({ code: "vault_file_type_denied" });
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
