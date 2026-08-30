import { mkdtemp, mkdir, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { PathPolicy } from "../src/security/path-policy";

describe("PathPolicy on Windows", () => {
  it.each(["../other-user/a.md", "C:\\Windows\\win.ini", "vault\\..\\..\\secret", "\\\\server\\share\\x", "C:drive-relative", "%2e%2e/secret", "bad\u0000name"])(
    "rejects %s outside granted roots",
    async (candidate) => {
      const root = await mkdtemp(join(tmpdir(), "agent-path-root-"));
      try {
        const policy = await PathPolicy.create([root], { platform: "win32" });
        await expect(policy.resolveWritable(candidate)).rejects.toMatchObject({ code: "path_outside_grant" });
      } finally { await rm(root, { recursive: true, force: true }); }
    },
  );

  it("rejects a directory link that escapes its granted root", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-path-root-"));
    const outside = await mkdtemp(join(tmpdir(), "agent-path-outside-"));
    try {
      await mkdir(join(root, "inside"));
      try { await symlink(outside, join(root, "inside", "escape"), "junction"); } catch { return; }
      const policy = await PathPolicy.create([root], { platform: "win32" });
      await expect(policy.resolveWritable("inside/escape/file.md")).rejects.toMatchObject({ code: "path_outside_grant" });
    } finally {
      await rm(root, { recursive: true, force: true });
      await rm(outside, { recursive: true, force: true });
    }
  });
});
