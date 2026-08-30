import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PathPolicy } from "../src/security/path-policy";

describe("PathPolicy on POSIX", () => {
  it("allows normalized descendants and rejects traversal and absolute outsiders", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-posix-root-"));
    try {
      const policy = await PathPolicy.create([root], { platform: "posix" });
      await expect(policy.resolveWritable("notes/chapter.md")).resolves.toBe(join(root, "notes", "chapter.md"));
      await expect(policy.resolveWritable("../secret")).rejects.toMatchObject({ code: "path_outside_grant" });
      await expect(policy.resolveWritable("/etc/passwd")).rejects.toMatchObject({ code: "path_outside_grant" });
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
