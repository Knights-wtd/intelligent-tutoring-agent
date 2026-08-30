import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { SkillRepository } from "../src/skills/SkillRepository";

it("loads global and vault skills without a product count cap", async () => {
  const root = await mkdtemp(join(tmpdir(), "agent-skills-"));
  try {
    const globalRoot = join(root, "global"); const vaultRoot = join(root, "vault", ".claude", "skills");
    for (let index = 0; index < 75; index += 1) {
      const parent = index < 40 ? globalRoot : vaultRoot;
      const directory = join(parent, `skill-${index}`); await mkdir(directory, { recursive: true });
      await writeFile(join(directory, "SKILL.md"), `---\nname: skill-${index}\ndescription: Skill ${index}\n---\nDo work.\n`);
    }
    const repository = new SkillRepository({ globalRoots: [globalRoot], vaultRoots: [join(root, "vault")] });
    await repository.refresh();
    expect(repository.list()).toHaveLength(75);
  } finally { await rm(root, { recursive: true, force: true }); }
});
