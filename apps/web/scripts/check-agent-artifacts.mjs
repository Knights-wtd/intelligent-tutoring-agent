import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = fileURLToPath(new URL(".", import.meta.url));
const webRoot = resolve(scriptDirectory, "..");
const buildDirectoryArgumentIndex = process.argv.indexOf("--build-dir");
if (buildDirectoryArgumentIndex >= 0 && !process.argv[buildDirectoryArgumentIndex + 1]) {
  throw new Error("--build-dir requires a path");
}
const buildDirectory = buildDirectoryArgumentIndex >= 0
  ? resolve(process.cwd(), process.argv[buildDirectoryArgumentIndex + 1])
  : resolve(webRoot, ".next");

const vendorName = ["Clau", "dian"].join("");
const forbiddenMarkers = [
  vendorName,
  ["d190786d11cc0b067475", "dcffbf8c334ee565d208"].join(""),
  ["Permission is hereby granted", ", free of charge"].join(""),
  ["Copyright (c)", " 2025"].join(""),
  [vendorName, " commit"].join(""),
  [vendorName.toLowerCase(), "_commit"].join(""),
  [vendorName.toLowerCase(), "-commit"].join(""),
];

function artifactFiles(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name);
    return entry.isDirectory() ? artifactFiles(path) : [path];
  });
}

const utf8Decoder = new TextDecoder("utf-8", { fatal: true });

function decodedText(path) {
  try {
    return utf8Decoder.decode(readFileSync(path));
  } catch (error) {
    if (error instanceof TypeError) return null;
    throw error;
  }
}

const roots = [
  resolve(buildDirectory, "static"),
  resolve(buildDirectory, "server", "app"),
];
let filesScanned = 0;
let bytesScanned = 0;
for (const root of roots) {
  if (!existsSync(root)) {
    throw new Error(`Required Next.js artifact directory is missing: ${root}`);
  }
  let decodableFiles = 0;
  for (const path of artifactFiles(root)) {
    const content = decodedText(path);
    if (content === null) continue;
    decodableFiles += 1;
    filesScanned += 1;
    bytesScanned += statSync(path).size;
    for (const marker of forbiddenMarkers) {
      if (content.includes(marker)) {
        throw new Error(`Forbidden vendor/provenance marker found in emitted Web artifact: ${path}`);
      }
    }
  }
  if (decodableFiles === 0) {
    throw new Error(`No decodable artifacts were emitted under required directory: ${root}`);
  }
}

console.log(`Agent artifact gate passed: ${filesScanned} decodable files, ${bytesScanned} bytes scanned.`);
