import { opendir, readFile } from "node:fs/promises";
import { basename, join, relative } from "node:path";

export interface AgentSkill { id: string; name: string; description: string; body: string; path: string; source: "global" | "vault" | "configured"; }
export interface SkillRepositoryOptions { globalRoots?: readonly string[]; vaultRoots?: readonly string[]; configuredRoots?: readonly string[]; }

export class SkillRepository {
  private skills: AgentSkill[] = [];
  constructor(private readonly options: SkillRepositoryOptions) {}
  async refresh(): Promise<void> {
    const roots = [
      ...(this.options.globalRoots ?? []).map(path => ({ path, source: "global" as const })),
      ...(this.options.vaultRoots ?? []).map(path => ({ path: join(path, ".claude", "skills"), source: "vault" as const })),
      ...(this.options.configuredRoots ?? []).map(path => ({ path, source: "configured" as const })),
    ];
    const found: AgentSkill[] = [];
    for (const root of roots) {
      for (const path of await findSkillFiles(root.path)) {
        const document = await readFile(path, "utf8");
        const parsed = parseSkill(document, basename(path.replace(/[\\/]SKILL\.md$/i, "")));
        found.push({ id: `${root.source}:${relative(root.path, path).replace(/\\/g, "/")}`, path, source: root.source, ...parsed });
      }
    }
    this.skills = found.sort((left, right) => left.id.localeCompare(right.id));
  }
  list(): readonly AgentSkill[] { return this.skills.map(skill => ({ ...skill })); }
}

async function findSkillFiles(root: string): Promise<string[]> {
  const files: string[] = [];
  async function walk(path: string): Promise<void> {
    let directory;
    try { directory = await opendir(path); } catch (error) { if (isMissing(error)) return; throw error; }
    for await (const entry of directory) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (entry.isFile() && entry.name.toLowerCase() === "skill.md") files.push(child);
    }
  }
  await walk(root); return files;
}
function parseSkill(document: string, fallbackName: string): { name: string; description: string; body: string } {
  const normalized = document.replace(/\r\n?/g, "\n");
  if (!normalized.startsWith("---\n")) return { name: fallbackName, description: "", body: normalized };
  const end = normalized.indexOf("\n---\n", 4); if (end < 0) throw new TypeError("Invalid SKILL.md frontmatter");
  const metadata = Object.fromEntries(normalized.slice(4, end).split("\n").flatMap(line => { const index = line.indexOf(":"); return index < 0 ? [] : [[line.slice(0, index).trim(), line.slice(index + 1).trim()]]; }));
  return { name: metadata.name || fallbackName, description: metadata.description || "", body: normalized.slice(end + 5) };
}
function isMissing(error: unknown): boolean { return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT"; }
