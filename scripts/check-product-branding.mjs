import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const TEXT_EXTENSIONS = new Set([
  ".cjs",
  ".css",
  ".html",
  ".js",
  ".json",
  ".jsx",
  ".md",
  ".mjs",
  ".ps1",
  ".py",
  ".scss",
  ".sh",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".yaml",
  ".yml",
]);

const EXCLUDED_DIRECTORIES = new Set([
  ".codebase-memory",
  ".git",
  ".tmp",
  ".venv",
  "dist",
  "dist-electron",
  "dist-remote",
  "graft",
  "node_modules",
  "python-embed",
  "release",
]);

const HISTORICAL_PREFIXES = [
  "docs/adr/",
  "docs/superpowers/",
  "docs/test-reports/",
  "docs/HANDOFF.md",
];

const LTX_PROVIDER_CONTRACT_FILES = new Set([
  "backend/services/video_providers/descriptors.py",
  "docs/PROVIDERS.md",
]);

const LEGACY_PRODUCT_PATTERN =
  /LTX[ -]?Desktop|Lightricks|ltxdesktop|ltx-desktop|https?:\/\/(?:www\.)?ltx\.(?:io|video)/i;

function requestedRoot() {
  const index = process.argv.indexOf("--root");
  if (index === -1) return process.cwd();
  if (!process.argv[index + 1]) {
    throw new Error("--root requires a directory");
  }
  return path.resolve(process.argv[index + 1]);
}

async function collectFiles(root, current = root) {
  const files = [];
  for (const entry of await readdir(current, { withFileTypes: true })) {
    if (entry.isDirectory() && EXCLUDED_DIRECTORIES.has(entry.name)) continue;
    const fullPath = path.join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(root, fullPath)));
      continue;
    }
    if (!entry.isFile()) continue;
    if (!TEXT_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) continue;
    files.push(fullPath);
  }
  return files;
}

function isAllowed(relativePath, line) {
  const normalized = relativePath.replaceAll("\\", "/");
  const basename = path.posix.basename(normalized);

  if (
    normalized === "scripts/check-product-branding.mjs" ||
    normalized === "scripts/verify-release-artifacts.mjs"
  ) {
    return true;
  }
  if (basename === "LICENSE.txt" || basename === "NOTICES.md") return true;
  if (HISTORICAL_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
    return true;
  }
  if (/\.(?:spec|test)\.[cm]?[jt]sx?$/.test(normalized)) return true;
  if (normalized.includes("/tests/") || normalized.startsWith("backend/tests/")) {
    return true;
  }
  if (normalized.startsWith("electron/fixtures/hypergen-branding-guard/")) {
    return true;
  }
  const withoutModelReferences = line
    .replace(
      /https?:\/\/(?:github\.com\/Lightricks\/LTX-2(?:\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]*)?|huggingface\.co\/Lightricks(?:\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]*)?)?)/gi,
      "",
    )
    .replace(/\bLightricks\/(?:LTX|gemma)[A-Za-z0-9._-]*(?:#\d+)?\b/g, "");
  if (
    withoutModelReferences !== line &&
    !LEGACY_PRODUCT_PATTERN.test(withoutModelReferences)
  ) {
    return true;
  }
  if (
    LTX_PROVIDER_CONTRACT_FILES.has(normalized) &&
    /https?:\/\/(?:api|console|docs)\.ltx\.io(?:\/|\b)/i.test(line) &&
    !LEGACY_PRODUCT_PATTERN.test(
      line.replace(
        /https?:\/\/(?:api|console|docs)\.ltx\.io(?:\/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]*)?/gi,
        "",
      ),
    )
  ) {
    return true;
  }
  return false;
}

async function main() {
  const root = requestedRoot();
  const violations = [];

  for (const file of await collectFiles(root)) {
    const relativePath = path.relative(root, file).replaceAll("\\", "/");
    const lines = (await readFile(file, "utf8")).split(/\r?\n/u);
    for (const [index, line] of lines.entries()) {
      if (!LEGACY_PRODUCT_PATTERN.test(line)) continue;
      if (isAllowed(relativePath, line)) continue;
      violations.push(`${relativePath}:${index + 1}: ${line.trim()}`);
    }
  }

  if (violations.length > 0) {
    console.error("Product-owned legacy branding found:");
    for (const violation of violations) console.error(violation);
    process.exitCode = 1;
    return;
  }

  console.log("HyperGen product branding check passed.");
}

await main();
