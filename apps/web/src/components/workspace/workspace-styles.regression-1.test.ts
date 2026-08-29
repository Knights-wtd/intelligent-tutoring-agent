import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Regression: ISSUE-001 — Knowledge and question-bank controls lost every CSS Module class.
// Found by /qa on 2026-08-22.
// Report: findings.md
describe("workspace CSS Module contract", () => {
  it("defines every class referenced by the workspace feature components", () => {
    const componentSources = [
      "workspace-shell.tsx",
      "knowledge-panel.tsx",
      "question-bank-panel.tsx",
    ].map((name) =>
      readFileSync(path.join(process.cwd(), "src/components/workspace", name), "utf8"),
    );
    const stylesheet = readFileSync(
      path.join(process.cwd(), "src/components/workspace/workspace-shell.module.css"),
      "utf8",
    );

    const referenced = new Set(
      componentSources.flatMap((source) =>
        [...source.matchAll(/styles\.([A-Za-z_][A-Za-z0-9_]*)/g)].map(
          (match) => match[1],
        ),
      ),
    );
    const defined = new Set(
      [...stylesheet.matchAll(/\.([A-Za-z_][A-Za-z0-9_-]*)/g)].map(
        (match) => match[1],
      ),
    );

    expect([...referenced].filter((className) => !defined.has(className))).toEqual([]);
  });

  it("keeps the approved lavender-light workspace tokens and responsive contract", () => {
    // 2026-08-28: palette re-approved as LAVENDER-LIGHT (original light theme
    // tinted toward purple to match the /welcome intro and auth pages).
    // Structural/responsive assertions below are unchanged.
    const stylesheet = readFileSync(
      path.join(process.cwd(), "src/components/workspace/workspace-shell.module.css"),
      "utf8",
    );

    expect(stylesheet).toContain("--bg: #faf9fe");
    expect(stylesheet).toContain("--purple: #6558c9");
    expect(stylesheet).toContain("--green: #167c59");
    expect(stylesheet).not.toMatch(/\.panelGroup\s*\{[^}]*min-width:\s*(?:900|820|760)px/s);
    expect(stylesheet).not.toMatch(/\.shell\s*\{[^}]*min-width:\s*[1-9]\d{2,}px/s);
    expect(stylesheet).toContain("@media (max-width: 1279px)");
    expect(stylesheet).toContain("@media (max-width: 959px)");
    expect(stylesheet).toContain("@media (max-width: 719px)");
    expect(stylesheet).toMatch(/\.drawerBackdrop\s*\{[^}]*position:\s*fixed/s);
    expect(stylesheet).toMatch(/@media \(max-width: 719px\)[\s\S]*min-height:\s*44px/s);
    expect(stylesheet).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
