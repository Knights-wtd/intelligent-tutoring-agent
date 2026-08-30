// @vitest-environment node

import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

const scriptPath = fileURLToPath(new URL("./check-agent-artifacts.mjs", import.meta.url));
const temporaryDirectories: string[] = [];
const forbiddenVendor = ["Clau", "dian"].join("");

function buildFixture(injectedRelativePath?: string): string {
  const root = mkdtempSync(resolve(tmpdir(), "agent-artifact-gate-"));
  temporaryDirectories.push(root);
  mkdirSync(resolve(root, "static"), { recursive: true });
  mkdirSync(resolve(root, "server", "app"), { recursive: true });
  writeFileSync(resolve(root, "static", "safe.js"), "console.log('safe')");
  writeFileSync(resolve(root, "server", "app", "safe.rsc"), "safe payload");
  if (injectedRelativePath) {
    const target = resolve(root, injectedRelativePath);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `visible ${forbiddenVendor} provenance`);
  }
  return root;
}

function runGate(buildDirectory: string) {
  return spawnSync(process.execPath, [scriptPath, "--build-dir", buildDirectory], {
    encoding: "utf8",
  });
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("Agent build artifact gate", () => {
  it.each([
    "static/media/injected.svg",
    "server/app/injected.meta",
    "server/app/injected.body",
  ])("rejects a forbidden marker injected into %s", (relativePath) => {
    const result = runGate(buildFixture(relativePath));

    expect(result.status).toBe(1);
    expect(`${result.stdout}${result.stderr}`).toContain(
      "Forbidden vendor/provenance marker found in emitted Web artifact",
    );
  });

  it.each([
    ["static", "static"],
    ["server/app", "server/app"],
  ])("rejects when the required %s root is missing", (_label, relativePath) => {
    const root = buildFixture();
    rmSync(resolve(root, relativePath), { recursive: true, force: true });

    const result = runGate(root);

    expect(result.status).toBe(1);
    expect(`${result.stdout}${result.stderr}`).toContain("Required Next.js artifact directory is missing");
  });

  it.each([
    ["static", "static/safe.js", "static/invalid.bin"],
    ["server/app", "server/app/safe.rsc", "server/app/invalid.bin"],
  ])("rejects when the required %s root contains only non-UTF-8 artifacts", (_label, safePath, binaryPath) => {
    const root = buildFixture();
    rmSync(resolve(root, safePath), { force: true });
    writeFileSync(resolve(root, binaryPath), Buffer.from([0xff, 0xfe, 0xfd]));

    const result = runGate(root);

    expect(result.status).toBe(1);
    expect(`${result.stdout}${result.stderr}`).toContain(
      "No decodable artifacts were emitted under required directory",
    );
  });

  it("passes when both required roots contain only safe decodable artifacts", () => {
    const result = runGate(buildFixture());

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("Agent artifact gate passed");
  });
});