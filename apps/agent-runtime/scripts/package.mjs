import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, parse, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(runtimeRoot, "../..");
const protocolRoot = join(repositoryRoot, "packages", "agent-protocol");
const defaultOutput = join(repositoryRoot, "artifacts", "agent-runtime");
const requestedOutput = readOutputArgument(process.argv.slice(2)) ?? defaultOutput;
const outputRoot = isAbsolute(requestedOutput)
  ? resolve(requestedOutput)
  : resolve(runtimeRoot, requestedOutput);

assertSafeOutput(outputRoot);
buildProtocol();
buildRuntime();
await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });

for (const source of [
  "dist",
  "package.json",
  "UPSTREAM.md",
  "PATCHES.md",
  "FILES.json",
  "THIRD_PARTY_NOTICES.md",
  "licenses",
]) {
  const from = join(runtimeRoot, source);
  const to = join(outputRoot, source);
  const metadata = await stat(from);
  await mkdir(dirname(to), { recursive: true });
  if (metadata.isDirectory()) await cp(from, to, { recursive: true, force: false });
  else await cp(from, to, { force: false });
}

const packagedProtocolRoot = join(outputRoot, "packages", "agent-protocol");
await mkdir(packagedProtocolRoot, { recursive: true });
await cp(join(protocolRoot, "dist"), join(packagedProtocolRoot, "dist"), {
  recursive: true,
  force: false,
});
const protocolPackageJson = JSON.parse(await readFile(join(protocolRoot, "package.json"), "utf8"));
delete protocolPackageJson.devDependencies;
delete protocolPackageJson.scripts;
await writeFile(
  join(packagedProtocolRoot, "package.json"),
  `${JSON.stringify(protocolPackageJson, null, 2)}
`,
  "utf8",
);

const packageJson = JSON.parse(await readFile(join(outputRoot, "package.json"), "utf8"));
delete packageJson.devDependencies;
packageJson.dependencies["@textbook-agent/agent-protocol"] = "file:packages/agent-protocol";
packageJson.scripts = { start: "node dist/index.js" };
await writeFile(join(outputRoot, "package.json"), `${JSON.stringify(packageJson, null, 2)}\n`, "utf8");

const manifest = {};
for (const file of await walk(outputRoot)) {
  if (file === "SHA256SUMS.json") continue;
  assertPublishable(file);
  const bytes = await readFile(join(outputRoot, file));
  manifest[file] = createHash("sha256").update(bytes).digest("hex");
}
await writeFile(
  join(outputRoot, "SHA256SUMS.json"),
  `${JSON.stringify(Object.fromEntries(Object.entries(manifest).sort()), null, 2)}\n`,
  "utf8",
);
process.stdout.write(`${outputRoot}\n`);

function buildProtocol() {
  const compiler = join(protocolRoot, "node_modules", "typescript", "bin", "tsc");
  const result = spawnSync(process.execPath, [compiler, "-p", "tsconfig.build.json"], {
    cwd: protocolRoot,
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    process.stderr.write(result.stdout ?? "");
    process.stderr.write(result.stderr ?? "");
    if (result.error) process.stderr.write(`${result.error.stack ?? result.error.message}
`);
    process.exit(result.status ?? 1);
  }
}

function buildRuntime() {
  const compiler = join(runtimeRoot, "node_modules", "typescript", "bin", "tsc");
  const result = spawnSync(process.execPath, [compiler, "-p", "tsconfig.build.json"], {
    cwd: runtimeRoot,
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    process.stderr.write(result.stdout ?? "");
    process.stderr.write(result.stderr ?? "");
    if (result.error) process.stderr.write(`${result.error.stack ?? result.error.message}\n`);
    process.exit(result.status ?? 1);
  }
}

function readOutputArgument(args) {
  const index = args.indexOf("--output");
  if (index === -1) return undefined;
  if (!args[index + 1]) throw new Error("--output requires a path");
  return args[index + 1];
}

function assertSafeOutput(target) {
  const filesystemRoot = parse(target).root;
  if (target === runtimeRoot || target === repositoryRoot || target === filesystemRoot) {
    throw new Error(`Refusing unsafe package output path: ${target}`);
  }
}

async function walk(root, prefix = "") {
  const result = [];
  for (const entry of await readdir(join(root, prefix), { withFileTypes: true })) {
    const file = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) result.push(...await walk(root, file));
    else result.push(file.replaceAll("\\", "/"));
  }
  return result;
}

function assertPublishable(file) {
  const normalized = file.replaceAll("\\", "/").toLowerCase();
  const segments = normalized.split("/");
  const basename = segments.at(-1) ?? "";
  const isSecretEnv = basename === ".env" || basename.startsWith(".env.");
  const isRuntimeState = segments.includes("sessions.json")
    || segments.includes("runtime.pid")
    || segments.includes("sidecars")
    || normalized.startsWith("vault/")
    || normalized.includes("/.agent-data/vault/");
  if (isSecretEnv || isRuntimeState) {
    throw new Error(`Forbidden runtime data in release package: ${file}`);
  }
}
