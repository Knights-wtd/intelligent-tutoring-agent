import {
  createCliPathFingerprintInputs,
  hasCliPathFingerprintInputs,
} from "../../src/claudian/src/core/providers/cli/CliPathFingerprintInputs";
import {
  validateAgentSkillInput,
  validateAgentSkillName,
} from "../../src/claudian/src/core/skills/validateAgentSkill";

describe("Claudian provider and skill input conformance", () => {
  it("trims host-specific and legacy CLI path candidates independently", () => {
    const inputs = createCliPathFingerprintInputs(
      " C:\\Program Files\\Claude\\claude.exe ",
      " /usr/local/bin/claude ",
    );

    expect(inputs).toEqual({
      hostnameCliPath: "C:\\Program Files\\Claude\\claude.exe",
      legacyCliPath: "/usr/local/bin/claude",
    });
    expect(hasCliPathFingerprintInputs(inputs)).toBe(true);
    expect(hasCliPathFingerprintInputs(createCliPathFingerprintInputs(undefined, "  "))).toBe(false);
  });

  it("requires portable skill names and non-empty instructions", () => {
    expect(validateAgentSkillName("code-review")).toBeNull();
    expect(validateAgentSkillName("Code Review")).toMatch(/lowercase letters or numbers/);
    expect(() => validateAgentSkillInput({
      name: "code-review",
      description: "Review code",
      instructions: "   ",
    })).toThrow("Skill instructions are required");
  });
});
