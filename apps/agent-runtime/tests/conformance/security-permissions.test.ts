import {
  getActionPattern,
  matchesRulePattern,
} from "../../src/claudian/src/core/security/approvalRules";
import { buildPersistentPermissionUpdates } from "../../src/claudian/src/providers/claude/security/ClaudePermissionUpdates";

describe("Claudian permission and path conformance", () => {
  it("keeps Bash approval exact unless an explicit wildcard is present", () => {
    expect(matchesRulePattern("Bash", "git status", "git status")).toBe(true);
    expect(matchesRulePattern("Bash", "git status --short", "git status")).toBe(false);
    expect(matchesRulePattern("Bash", "git status --short", "git *")).toBe(true);
  });

  it("normalizes Windows separators while preserving path segment boundaries", () => {
    expect(matchesRulePattern("Read", "C:\\vault\\notes\\one.md", "C:/vault/notes")).toBe(true);
    expect(matchesRulePattern("Read", "C:\\vault\\notes-private\\one.md", "C:/vault/notes")).toBe(false);
  });

  it("persists only scoped allow suggestions at project level", () => {
    expect(buildPersistentPermissionUpdates("Read", {}, [{
      type: "addRules",
      behavior: "deny",
      rules: [
        { toolName: "Read", ruleContent: "   " },
        { toolName: "Read", ruleContent: "/approved/*" },
      ],
      destination: "session",
    }])).toEqual([{
      type: "addRules",
      behavior: "allow",
      rules: [{ toolName: "Read", ruleContent: "/approved/*" }],
      destination: "projectSettings",
    }]);
    expect(getActionPattern("Bash", { command: "  git status  " })).toBe("git status");
  });
});
