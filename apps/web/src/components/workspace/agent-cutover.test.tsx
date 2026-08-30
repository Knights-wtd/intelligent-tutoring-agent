import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const directory = dirname(fileURLToPath(import.meta.url));

describe("Agent workspace cutover", () => {
  it("removes the active TutorPanel path and leaves AgentPanel as the workspace AI surface", () => {
    const source = readFileSync(resolve(directory, "workspace-shell.tsx"), "utf8");

    expect(source).toContain("<AgentPanel");
    expect(source).not.toContain("TutorPanel");
    expect(source).not.toContain("assistantMode");
    expect(existsSync(resolve(directory, "tutor-panel.tsx"))).toBe(false);
  });
  it("keeps legacy Tutor access read-only in the Web client", () => {
    const source = readFileSync(resolve(directory, "../../lib/tutor-api.ts"), "utf8");

    expect(source).toContain("getConversation");
    expect(source).not.toContain("createConversation");
    expect(source).not.toContain("sendMessage");
    expect(source).not.toContain("/api/v1/tutor/status");
  });

});
