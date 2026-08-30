import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";

async function runPackage(output: string): Promise<void> {
  await new Promise<void>((resolvePromise, reject) => {
    const child = spawn(process.execPath, ["scripts/package.mjs", "--output", output], {
      cwd: resolve(__dirname, ".."),
      stdio: "pipe",
    });
    let stderr = "";
    child.stderr.on("data", chunk => { stderr += String(chunk); });
    child.once("error", reject);
    child.once("exit", code => code === 0
      ? resolvePromise()
      : reject(new Error(`package script exited ${code}: ${stderr}`)));
  });
}


async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolvePromise, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolvePromise);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Unable to allocate test port");
  await new Promise<void>((resolvePromise, reject) => server.close(error => error ? reject(error) : resolvePromise()));
  return address.port;
}

async function stopChild(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await new Promise<void>(resolvePromise => {
    const timeout = setTimeout(() => {
      child.kill("SIGKILL");
      resolvePromise();
    }, 3_000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolvePromise();
    });
  });
}

async function walk(root: string, prefix = ""): Promise<string[]> {
  const result: string[] = [];
  for (const entry of await readdir(join(root, prefix), { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) result.push(...await walk(root, relative));
    else result.push(relative.replaceAll("\\", "/"));
  }
  return result;
}

describe("agent runtime release package", () => {
  it("ships provenance and excludes secrets, sessions and sidecars", async () => {
    const root = await mkdtemp(join(tmpdir(), "agent-runtime-package-"));
    try {
      await runPackage(root);
      const files = await walk(root);
      expect(files).toContain("THIRD_PARTY_NOTICES.md");
      expect(files).toContain("licenses/claudian-MIT.txt");
      expect(files).toContain("FILES.json");
      expect(files).toContain("SHA256SUMS.json");
      expect(files.some(file => file.startsWith("dist/") && file.endsWith("index.js"))).toBe(true);
      expect(files).toContain("packages/agent-protocol/dist/index.js");
      expect(files).toContain("packages/agent-protocol/dist/index.d.ts");
      expect(files.some(file => /(?:^|\/)(?:\.env|sessions\.json|sidecars)(?:$|\/)/.test(file))).toBe(false);

      const runtimePackage = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as {
        dependencies?: Record<string, string>;
      };
      expect(runtimePackage.dependencies?.["@textbook-agent/agent-protocol"]).toBe("file:packages/agent-protocol");
      expect(runtimePackage.dependencies?.["@textbook-agent/agent-protocol"]).not.toContain("workspace:");

      const protocolPackage = JSON.parse(await readFile(join(root, "packages", "agent-protocol", "package.json"), "utf8")) as {
        main?: string;
        types?: string;
      };
      expect(protocolPackage.main).toBe("./dist/index.js");
      expect(protocolPackage.types).toBe("./dist/index.d.ts");

      const manifest = JSON.parse(await readFile(join(root, "SHA256SUMS.json"), "utf8")) as Record<string, string>;
      expect(manifest["UPSTREAM.md"]).toMatch(/^[a-f0-9]{64}$/);
    } finally { await rm(root, { recursive: true, force: true }); }
  });

  it("starts the compiled Node entry point and serves health without loading TypeScript sources", async () => {
    const runtimeRoot = resolve(__dirname, "..");
    const sidecarRoot = await mkdtemp(join(tmpdir(), "agent-runtime-entry-"));
    const port = await freePort();
    const child = spawn(process.execPath, ["dist/index.js"], {
      cwd: runtimeRoot,
      env: {
        ...process.env,
        AGENT_RUNTIME_HOST: "127.0.0.1",
        AGENT_RUNTIME_PORT: String(port),
        AGENT_RUNTIME_TOKEN: "entry-test-token",
        AGENT_RUNTIME_CAPABILITY_SECRET: "entry-test-capability",
        AGENT_RUNTIME_SIDECAR_ROOT: sidecarRoot,
      },
      stdio: "pipe",
    });
    let stderr = "";
    child.stderr?.on("data", chunk => { stderr += String(chunk); });

    try {
      const deadline = Date.now() + 10_000;
      let response: Response | undefined;
      while (Date.now() < deadline && child.exitCode === null) {
        try {
          response = await fetch(`http://127.0.0.1:${port}/v1/health`);
          if (response.ok) break;
        } catch {}
        await new Promise(resolvePromise => setTimeout(resolvePromise, 100));
      }
      expect(child.exitCode).toBeNull();
      expect(response?.status).toBe(200);
      await expect(response?.json()).resolves.toMatchObject({
        status: "ok",
        protocol_version: "1.0",
      });
    } catch (error) {
      throw new Error(`${String(error)}\nRuntime stderr:\n${stderr}`);
    } finally {
      await stopChild(child);
      await rm(sidecarRoot, { recursive: true, force: true });
    }
  }, 20_000);

  it("keeps upstream provenance strings out of web source", async () => {
    const webRoot = resolve(__dirname, "../../web/src");
    const files = await walk(webRoot);
    const contents = await Promise.all(files.map(file => readFile(join(webRoot, file), "utf8")));
    expect(contents.join("\n")).not.toContain("d190786d11cc0b067475dcffbf8c334ee565d208");
    expect(contents.join("\n")).not.toContain("Claudian");
  });
});
