import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { BashTool } from "../src/tools/bash/BashTool";
import { PathPolicy } from "../src/security/path-policy";

describe("BashTool", () => {
  it("automatically executes in a granted root and redacts secret environment values from audit", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-bash-"));
    try {
      const policy = await PathPolicy.create([root]);
      const audits: unknown[] = [];
      const tool = new BashTool({ pathPolicy: policy, onAudit: event => audits.push(event) });
      const result = await tool.run({
        command: `"${process.execPath}" -e "process.stdout.write(process.cwd())"`,
        cwd: ".",
        environment: { AGENT_API_TOKEN: "super-secret" },
      });
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe(root);
      expect(JSON.stringify(audits)).not.toContain("super-secret");
      expect(JSON.stringify(audits)).toContain("[REDACTED]");
    } finally { await rm(root, { recursive: true, force: true }); }
  });
});
