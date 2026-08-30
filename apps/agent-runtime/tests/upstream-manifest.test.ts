import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

interface VendoredFile {
  path: string;
  sha256: string;
}

interface UpstreamManifest {
  upstreamRepository: string;
  upstreamVersion: string;
  upstreamCommit: string;
  upstreamTreeSha256: string;
  files: VendoredFile[];
}

const runtimeRoot = path.resolve(__dirname, "..");
const manifestPath = path.join(runtimeRoot, "FILES.json");

function sha256(filePath: string): string {
  return createHash("sha256").update(readFileSync(filePath)).digest("hex");
}

function loadManifest(): UpstreamManifest {
  return JSON.parse(readFileSync(manifestPath, "utf8")) as UpstreamManifest;
}

describe("Claudian upstream manifest", () => {
  it("pins the approved Claudian source archive", () => {
    const manifest = loadManifest();

    expect(manifest.upstreamRepository).toBe("https://github.com/YishenTu/claudian");
    expect(manifest.upstreamVersion).toBe("2.2.4");
    expect(manifest.upstreamCommit).toBe("d190786d11cc0b067475dcffbf8c334ee565d208");
    expect(manifest.upstreamTreeSha256).toBe(
      "abc305a71cdf700b7b7721aae0dd9d9c5bface24d6b5d40f24c993ab869933c8",
    );
    expect(manifest.files.length).toBeGreaterThan(0);
    expect(manifest.files.map(file => file.path)).toEqual(
      [...manifest.files.map(file => file.path)].sort((left, right) => left.localeCompare(right, "en")),
    );
    expect(manifest.files.every(file => /^[a-f0-9]{64}$/.test(file.sha256))).toBe(true);
  });

  it("matches every vendored file and excludes the Obsidian UI entry point", () => {
    const manifest = loadManifest();

    expect(manifest.files.some(file => /(^|\/)main\.ts$/.test(file.path))).toBe(false);
    expect(manifest.files.some(file => file.path.startsWith("src/features/"))).toBe(false);

    for (const file of manifest.files) {
      const vendoredPath = path.join(runtimeRoot, "src", "claudian", ...file.path.split("/"));
      expect(sha256(vendoredPath)).toBe(file.sha256);
    }
  });
});
