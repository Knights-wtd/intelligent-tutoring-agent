jest.mock(
  "../../src/claudian/src/utils/agent",
  () => ({ serializeAgent: (agent: { name: string }) => `agent:${agent.name}` }),
  { virtual: true },
);
jest.mock(
  "../../src/claudian/src/providers/claude/agents/AgentStorage",
  () => ({
    parseAgentFile: () => null,
    buildAgentFromFrontmatter: () => null,
  }),
  { virtual: true },
);
jest.mock(
  "../../src/claudian/src/utils/slashCommand",
  () => ({
    parseSlashCommandContent: () => ({}),
    parsedToSlashCommand: () => ({}),
    serializeCommand: (skill: { name: string }) => `skill:${skill.name}`,
  }),
  { virtual: true },
);

import type { VaultFileAdapter } from "../../src/claudian/src/core/storage/VaultFileAdapter";
import { AgentVaultStorage } from "../../src/claudian/src/providers/claude/storage/AgentVaultStorage";
import { SkillStorage } from "../../src/claudian/src/providers/claude/storage/SkillStorage";

function createAdapter(): jest.Mocked<VaultFileAdapter> {
  return {
    write: jest.fn().mockResolvedValue(undefined),
    delete: jest.fn().mockResolvedValue(undefined),
    deleteFolder: jest.fn().mockResolvedValue(undefined),
    ensureFolder: jest.fn().mockResolvedValue(undefined),
    exists: jest.fn().mockResolvedValue(false),
    listFiles: jest.fn().mockResolvedValue([]),
    listFolders: jest.fn().mockResolvedValue([]),
    read: jest.fn(),
  } as unknown as jest.Mocked<VaultFileAdapter>;
}

describe("Claudian vault storage boundary conformance", () => {
  it("normalizes a Windows agent file path back to the managed vault path", async () => {
    const adapter = createAdapter();
    const storage = new AgentVaultStorage(adapter);

    await storage.save({
      id: "reviewer",
      name: "reviewer",
      description: "Reviews changes",
      prompt: "Review carefully",
      source: "vault",
      filePath: "C:\\vault\\.claude\\agents\\reviewer.md",
    });

    expect(adapter.write).toHaveBeenCalledWith(
      ".claude/agents/reviewer.md",
      "agent:reviewer",
    );
  });

  it("keeps skill writes and deletion inside the managed skill directory", async () => {
    const adapter = createAdapter();
    const storage = new SkillStorage(adapter);
    const skill = {
      id: "skill-review",
      name: "review",
      description: "Review code",
      content: "Review carefully",
    };

    await storage.save(skill);
    await storage.delete(skill.id);

    expect(adapter.ensureFolder).toHaveBeenCalledWith(".claude/skills/review");
    expect(adapter.write).toHaveBeenCalledWith(".claude/skills/review/SKILL.md", "skill:review");
    expect(adapter.delete).toHaveBeenCalledWith(".claude/skills/review/SKILL.md");
    expect(adapter.deleteFolder).toHaveBeenCalledWith(".claude/skills/review");
  });
});
