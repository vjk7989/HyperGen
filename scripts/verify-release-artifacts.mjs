import { load as loadYaml } from "js-yaml";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { computeFileSha256, verifyRuntimeArchiveFile } from "./release-artifacts.mjs";

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const MAX_RELEASE_ASSET_SIZE = 2_000_000_000;
const MAX_METADATA_SIZE = 16 * 1024 * 1024;

function usage() {
  return `Usage: node scripts/verify-release-artifacts.mjs [options]

Options:
  --artifacts-dir <dir>   Directory containing downloaded release assets
  --release-tag <tag>     Verify a GitHub draft without downloading large assets
  --repo <owner/repo>     GitHub repository for --release-tag
  --expected-commit <sha> Expected draft target (defaults to GITHUB_SHA)
  --contract <file>       Release contract JSON
  --manifest <file>       Verify one runtime manifest instead of a release
  --parts-dir <dir>       Parts directory for --manifest
  --expected-checksum <h> Expected archive checksum for --manifest
  --updater-metadata <f> Verify one latest*.yml against local packages
  --packages-dir <dir>    Package directory for --updater-metadata
  --expected-version <v> Expected version for --updater-metadata
  --help                  Show this help
`;
}

function parseArguments(argv) {
  const options = {};
  const flags = new Map([
    ["--artifacts-dir", "artifactsDir"],
    ["--release-tag", "releaseTag"],
    ["--repo", "repo"],
    ["--expected-commit", "expectedCommit"],
    ["--contract", "contractPath"],
    ["--manifest", "manifestPath"],
    ["--parts-dir", "partsDirectory"],
    ["--expected-checksum", "expectedChecksum"],
    ["--updater-metadata", "updaterMetadata"],
    ["--packages-dir", "packagesDirectory"],
    ["--expected-version", "expectedVersion"],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help") return { help: true };
    const key = flags.get(flag);
    if (!key) throw new Error(`Unknown option: ${flag}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${flag}`);
    options[key] = value;
    index += 1;
  }
  return options;
}

async function walkFiles(root) {
  const files = [];
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(fullPath);
      else if (entry.isFile()) files.push(fullPath);
    }
  }
  await visit(root);
  return files;
}

function indexByBasename(files) {
  const index = new Map();
  for (const filePath of files) {
    const name = path.basename(filePath);
    const existing = index.get(name) ?? [];
    existing.push(filePath);
    index.set(name, existing);
  }
  return index;
}

function requireUnique(index, name) {
  const matches = index.get(name) ?? [];
  if (matches.length === 0) throw new Error(`Missing release asset: ${name}`);
  if (matches.length > 1) throw new Error(`Duplicate release asset: ${name}`);
  return matches[0];
}

async function verifyChecksumFiles(checksumFiles, allFiles, requiredFiles) {
  if (checksumFiles.length === 0) throw new Error("Missing release SHA256SUMS asset");
  const globalIndex = indexByBasename(allFiles);
  const covered = new Set();

  for (const checksumPath of checksumFiles) {
    const lines = (await readFile(checksumPath, "utf8"))
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) throw new Error(`Checksum file is empty: ${checksumPath}`);
    const seen = new Set();
    for (const line of lines) {
      const match = /^([a-fA-F0-9]{64})\s+\*?(.+)$/.exec(line);
      if (!match) throw new Error(`Malformed checksum entry in ${checksumPath}: ${line}`);
      const expected = match[1].toLowerCase();
      const listedName = match[2].trim();
      if (path.isAbsolute(listedName) || listedName.split(/[\\/]/).includes("..")) {
        throw new Error(`Unsafe checksum path in ${checksumPath}: ${listedName}`);
      }
      if (seen.has(listedName))
        throw new Error(`Duplicate checksum entry: ${listedName}`);
      seen.add(listedName);

      const nearby = path.resolve(path.dirname(checksumPath), listedName);
      let target;
      try {
        if ((await stat(nearby)).isFile()) target = nearby;
      } catch {
        const matches = globalIndex.get(path.basename(listedName)) ?? [];
        if (matches.length === 1) target = matches[0];
      }
      if (!target)
        throw new Error(`Checksum target is missing or ambiguous: ${listedName}`);
      if ((await computeFileSha256(target)) !== expected) {
        throw new Error(`Checksum mismatch for release asset: ${listedName}`);
      }
      covered.add(path.resolve(target));
    }
  }

  for (const required of requiredFiles) {
    if (!covered.has(path.resolve(required))) {
      throw new Error(
        `Release asset is not covered by SHA256SUMS: ${path.basename(required)}`,
      );
    }
  }
}

function validateUpdaterMetadata(source, name, version) {
  if (
    !new RegExp(
      `^version:\\s*["']?${version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["']?\\s*$`,
      "m",
    ).test(source)
  ) {
    throw new Error(`Updater metadata has the wrong version: ${name}`);
  }
  if (!/HyperGen/.test(source)) {
    throw new Error(`Updater metadata does not reference HyperGen: ${name}`);
  }
  if (/LTX Desktop|Lightricks/i.test(source)) {
    throw new Error(`Updater metadata contains legacy product branding: ${name}`);
  }
}

async function sha512File(filePath) {
  const hash = createHash("sha512");
  for await (const chunk of createReadStream(filePath)) hash.update(chunk);
  return hash.digest("base64");
}

function updaterPackageName(reference, metadataName) {
  if (typeof reference !== "string" || reference.trim() === "") {
    throw new Error(`Updater metadata has an invalid package URL: ${metadataName}`);
  }
  let pathname;
  try {
    const parsed = new URL(reference, "https://updates.hypergen.invalid/");
    if (parsed.origin !== "https://updates.hypergen.invalid") {
      throw new Error("remote URL");
    }
    pathname = decodeURIComponent(parsed.pathname);
  } catch {
    throw new Error(`Updater metadata has an unsafe package URL: ${reference}`);
  }
  const name = path.posix.basename(pathname);
  if (!name || name === "." || name === ".." || /[\\/]/.test(name)) {
    throw new Error(`Updater metadata has an unsafe package name: ${reference}`);
  }
  if (!/HyperGen/.test(name) || /LTX Desktop|Lightricks/i.test(name)) {
    throw new Error(`Updater package has invalid product branding: ${name}`);
  }
  return name;
}

/** Validate native updater metadata against packages produced in the same job. */
export async function verifyLocalUpdaterMetadata({
  metadataPath,
  packagesDirectory,
  expectedVersion,
}) {
  if (!metadataPath) throw new Error("Updater metadata path is required");
  const resolvedMetadata = path.resolve(metadataPath);
  const packageRoot = path.resolve(packagesDirectory ?? path.dirname(resolvedMetadata));
  const source = await readFile(resolvedMetadata, "utf8");
  const metadataName = path.basename(resolvedMetadata);
  const document = loadYaml(source);
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new Error(`Updater metadata must be a YAML object: ${metadataName}`);
  }
  const version = String(document.version ?? "");
  if (!version || (expectedVersion && version !== expectedVersion)) {
    throw new Error(`Updater metadata has the wrong version: ${metadataName}`);
  }
  validateUpdaterMetadata(source, metadataName, expectedVersion ?? version);
  if (!Array.isArray(document.files) || document.files.length === 0) {
    throw new Error(`Updater metadata has no package files: ${metadataName}`);
  }

  const verified = new Map();
  for (const entry of document.files) {
    if (!entry || typeof entry !== "object") {
      throw new Error(`Updater metadata has an invalid file entry: ${metadataName}`);
    }
    const name = updaterPackageName(entry.url, metadataName);
    if (verified.has(name)) throw new Error(`Updater metadata repeats package: ${name}`);
    if (!Number.isSafeInteger(entry.size) || entry.size <= 0) {
      throw new Error(`Updater metadata has an invalid package size: ${name}`);
    }
    if (typeof entry.sha512 !== "string" || !/^[A-Za-z0-9+/]{86}==$/.test(entry.sha512)) {
      throw new Error(`Updater metadata has an invalid SHA-512 digest: ${name}`);
    }
    const packagePath = path.resolve(packageRoot, name);
    if (path.dirname(packagePath) !== packageRoot) {
      throw new Error(`Updater package path escapes package directory: ${name}`);
    }
    const packageInfo = await stat(packagePath);
    if (!packageInfo.isFile() || packageInfo.size !== entry.size) {
      throw new Error(`Updater package size does not match metadata: ${name}`);
    }
    const actualSha512 = await sha512File(packagePath);
    if (actualSha512 !== entry.sha512) {
      throw new Error(`Updater package SHA-512 does not match metadata: ${name}`);
    }
    verified.set(name, { size: entry.size, sha512: entry.sha512 });
  }

  const primaryName = updaterPackageName(document.path, metadataName);
  const primary = verified.get(primaryName);
  if (!primary) {
    throw new Error(`Updater primary package is missing from files: ${primaryName}`);
  }
  if (document.sha512 !== primary.sha512) {
    throw new Error(`Updater primary SHA-512 does not match files entry: ${primaryName}`);
  }
  return {
    metadata: metadataName,
    version,
    packages: [...verified.keys()],
  };
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function parseChecksumText(source, checksumName) {
  const entries = new Map();
  const lines = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) throw new Error(`Checksum file is empty: ${checksumName}`);
  for (const line of lines) {
    const match = /^([a-fA-F0-9]{64})\s+\*?(.+)$/.exec(line);
    if (!match) throw new Error(`Malformed checksum entry in ${checksumName}: ${line}`);
    const name = match[2].trim();
    if (path.isAbsolute(name) || name.split(/[\\/]/).includes("..")) {
      throw new Error(`Unsafe checksum path in ${checksumName}: ${name}`);
    }
    const basename = path.basename(name);
    const checksum = match[1].toLowerCase();
    if (entries.has(basename)) {
      throw new Error(`Duplicate checksum entry in ${checksumName}: ${basename}`);
    }
    entries.set(basename, checksum);
  }
  return entries;
}

function validateHostedAsset(asset) {
  if (!asset || typeof asset !== "object" || typeof asset.name !== "string") {
    throw new Error("GitHub returned an invalid release asset");
  }
  if (!Number.isSafeInteger(asset.size) || asset.size <= 0) {
    throw new Error(`Release asset must be nonempty: ${asset.name}`);
  }
  if (asset.size >= MAX_RELEASE_ASSET_SIZE) {
    throw new Error(`Release asset exceeds the 2,000,000,000-byte limit: ${asset.name}`);
  }
  if (asset.state !== undefined && asset.state !== "uploaded") {
    throw new Error(`Release asset is not fully uploaded: ${asset.name}`);
  }
  const digest = /^sha256:([a-fA-F0-9]{64})$/.exec(asset.digest ?? "");
  if (!digest)
    throw new Error(`Release asset has no GitHub SHA-256 digest: ${asset.name}`);
  return digest[1].toLowerCase();
}

function requireHostedAsset(index, name) {
  const asset = index.get(name);
  if (!asset) throw new Error(`Missing release asset: ${name}`);
  return asset;
}

function requireChecksum(checksums, asset) {
  const expected = checksums.get(asset.name);
  if (!expected) {
    throw new Error(`Release asset is not covered by platform SHA256SUMS: ${asset.name}`);
  }
  const digest = validateHostedAsset(asset);
  if (digest !== expected) {
    throw new Error(`GitHub asset digest does not match SHA256SUMS: ${asset.name}`);
  }
  return digest;
}

function validateRemoteManifest(manifest, prefix) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error(`Invalid runtime manifest: ${prefix}`);
  }
  if (!Number.isSafeInteger(manifest.totalSize) || manifest.totalSize <= 0) {
    throw new Error(`Runtime manifest has an invalid total size: ${prefix}`);
  }
  if (
    typeof manifest.sha256 !== "string" ||
    !SHA256_PATTERN.test(manifest.sha256.toLowerCase())
  ) {
    throw new Error(`Runtime manifest has an invalid archive checksum: ${prefix}`);
  }
  if (!Array.isArray(manifest.parts) || manifest.parts.length === 0) {
    throw new Error(`Runtime manifest has no parts: ${prefix}`);
  }
  let totalSize = 0;
  manifest.parts.forEach((part, index) => {
    const expectedName = `${prefix}.part${String(index + 1).padStart(3, "0")}`;
    if (part?.name !== expectedName) {
      throw new Error(`Runtime parts must be sequential: ${part?.name ?? "unknown"}`);
    }
    if (!Number.isSafeInteger(part.size) || part.size <= 0) {
      throw new Error(`Runtime part must be nonempty: ${part.name}`);
    }
    if (
      typeof part.sha256 !== "string" ||
      !SHA256_PATTERN.test(part.sha256.toLowerCase())
    ) {
      throw new Error(`Runtime part has an invalid checksum: ${part.name}`);
    }
    totalSize += part.size;
  });
  if (totalSize !== manifest.totalSize) {
    throw new Error(`Runtime manifest part sizes do not equal total size: ${prefix}`);
  }
  return manifest;
}

/**
 * Verify a GitHub release snapshot without downloading installers or runtime parts.
 * loadAsset is called only for small metadata assets.
 */
export async function verifyHostedReleaseSnapshot({
  release,
  contract,
  loadAsset,
  expectedCommit,
  resolvedCommit,
}) {
  if (!release || !Array.isArray(release.assets)) {
    throw new Error("GitHub returned an invalid release");
  }
  if (release.draft !== true) throw new Error("GitHub release must still be a draft");
  if (release.prerelease !== undefined && release.prerelease !== true) {
    throw new Error("GitHub preview release must be marked as a prerelease");
  }
  if (expectedCommit) {
    if (
      typeof expectedCommit !== "string" ||
      typeof resolvedCommit !== "string" ||
      resolvedCommit.toLowerCase() !== expectedCommit.toLowerCase()
    ) {
      throw new Error(
        `GitHub release tag commit does not match workflow commit: ${resolvedCommit ?? "unknown"}`,
      );
    }
  }
  if (!contract?.version || !contract?.platforms)
    throw new Error("Invalid release contract");
  if (typeof loadAsset !== "function")
    throw new Error("Asset metadata loader is required");

  const assets = new Map();
  for (const asset of release.assets) {
    if (assets.has(asset.name)) throw new Error(`Duplicate release asset: ${asset.name}`);
    validateHostedAsset(asset);
    if (/LTX Desktop|Lightricks/i.test(asset.name)) {
      throw new Error(`Release asset contains legacy product branding: ${asset.name}`);
    }
    assets.set(asset.name, asset);
  }

  const checksumAssets = release.assets.filter((asset) =>
    /(?:^|\.)SHA256SUMS$/.test(asset.name),
  );
  if (checksumAssets.length === 0) throw new Error("Missing release SHA256SUMS asset");
  const checksumMaps = new Map();
  const allDeclaredChecksums = new Map();
  const expectedNames = new Set(checksumAssets.map((asset) => asset.name));
  for (const asset of checksumAssets) {
    if (asset.size > MAX_METADATA_SIZE) {
      throw new Error(`Checksum metadata is unexpectedly large: ${asset.name}`);
    }
    const content = await loadAsset(asset);
    if (!Buffer.isBuffer(content))
      throw new Error(`Invalid metadata content: ${asset.name}`);
    if (
      content.length !== asset.size ||
      sha256Buffer(content) !== validateHostedAsset(asset)
    ) {
      throw new Error(`Downloaded metadata does not match GitHub digest: ${asset.name}`);
    }
    const entries = parseChecksumText(content.toString("utf8"), asset.name);
    for (const [name, checksum] of entries) {
      const previous = allDeclaredChecksums.get(name);
      if (previous && previous !== checksum) {
        throw new Error(`Platform checksum files disagree for ${name}`);
      }
      allDeclaredChecksums.set(name, checksum);
    }
    checksumMaps.set(asset.name, entries);
  }

  const updaterAssets = [];
  const runtimeResults = [];
  let dependencyHashAsset;

  for (const platform of Object.values(contract.platforms)) {
    if (!Array.isArray(platform.packages)) {
      throw new Error("Invalid platform package inventory");
    }
    const packageAssets = platform.packages.map((name) => {
      if (/LTX Desktop|Lightricks/i.test(name)) {
        throw new Error(`Release contract contains legacy product branding: ${name}`);
      }
      const asset = requireHostedAsset(assets, name);
      expectedNames.add(name);
      return asset;
    });
    for (const asset of packageAssets) {
      if (/^latest(?:-linux|-mac)?\.yml$/.test(asset.name)) {
        updaterAssets.push({
          asset,
          allowedPackages: new Set(packageAssets.map((item) => item.name)),
        });
      }
    }

    let platformChecksums;
    if (platform.runtimePrefix) {
      const checksumName = `${platform.runtimePrefix}.SHA256SUMS`;
      platformChecksums = checksumMaps.get(checksumName);
      if (!platformChecksums)
        throw new Error(`Missing platform checksums: ${checksumName}`);

      const manifestAsset = requireHostedAsset(
        assets,
        `${platform.runtimePrefix}.manifest.json`,
      );
      expectedNames.add(manifestAsset.name);
      if (manifestAsset.size > MAX_METADATA_SIZE) {
        throw new Error(`Runtime manifest is unexpectedly large: ${manifestAsset.name}`);
      }
      requireChecksum(platformChecksums, manifestAsset);
      const manifestContent = await loadAsset(manifestAsset);
      if (
        !Buffer.isBuffer(manifestContent) ||
        manifestContent.length !== manifestAsset.size ||
        sha256Buffer(manifestContent) !== validateHostedAsset(manifestAsset)
      ) {
        throw new Error(
          `Downloaded metadata does not match GitHub digest: ${manifestAsset.name}`,
        );
      }
      const manifest = validateRemoteManifest(
        JSON.parse(manifestContent.toString("utf8")),
        platform.runtimePrefix,
      );
      for (const part of manifest.parts) {
        const partAsset = requireHostedAsset(assets, part.name);
        expectedNames.add(part.name);
        if (partAsset.size !== part.size) {
          throw new Error(
            `GitHub runtime part size does not match manifest: ${part.name}`,
          );
        }
        if (requireChecksum(platformChecksums, partAsset) !== part.sha256.toLowerCase()) {
          throw new Error(
            `GitHub runtime part digest does not match manifest: ${part.name}`,
          );
        }
      }
      runtimeResults.push({ prefix: platform.runtimePrefix, sha256: manifest.sha256 });
    } else {
      const candidates = [...checksumMaps.values()].filter((entries) =>
        packageAssets.every((asset) => entries.has(asset.name)),
      );
      if (candidates.length !== 1) {
        throw new Error("Could not identify one checksum file for platform packages");
      }
      [platformChecksums] = candidates;
    }
    for (const asset of packageAssets) requireChecksum(platformChecksums, asset);
  }

  dependencyHashAsset = requireHostedAsset(assets, "python-deps-hash.txt");
  expectedNames.add(dependencyHashAsset.name);
  if (dependencyHashAsset.size > MAX_METADATA_SIZE) {
    throw new Error("python-deps-hash.txt is unexpectedly large");
  }
  const dependencyHashChecksums = [...checksumMaps.values()].filter((entries) =>
    entries.has(dependencyHashAsset.name),
  );
  if (dependencyHashChecksums.length === 0) {
    throw new Error("python-deps-hash.txt is not covered by platform SHA256SUMS");
  }
  requireChecksum(dependencyHashChecksums[0], dependencyHashAsset);
  const dependencyHashContent = await loadAsset(dependencyHashAsset);
  if (
    !Buffer.isBuffer(dependencyHashContent) ||
    dependencyHashContent.length !== dependencyHashAsset.size ||
    sha256Buffer(dependencyHashContent) !== validateHostedAsset(dependencyHashAsset)
  ) {
    throw new Error("Downloaded python-deps-hash.txt does not match GitHub digest");
  }
  const dependencyHash = dependencyHashContent.toString("utf8").trim();
  if (!SHA256_PATTERN.test(dependencyHash)) {
    throw new Error("python-deps-hash.txt does not contain a SHA-256 checksum");
  }

  for (const { asset, allowedPackages } of updaterAssets) {
    if (asset.size > MAX_METADATA_SIZE) {
      throw new Error(`Updater metadata is unexpectedly large: ${asset.name}`);
    }
    const content = await loadAsset(asset);
    if (
      !Buffer.isBuffer(content) ||
      content.length !== asset.size ||
      sha256Buffer(content) !== validateHostedAsset(asset)
    ) {
      throw new Error(`Downloaded metadata does not match GitHub digest: ${asset.name}`);
    }
    const source = content.toString("utf8");
    validateUpdaterMetadata(source, asset.name, contract.version);
    const document = loadYaml(source);
    if (!document || typeof document !== "object" || !Array.isArray(document.files)) {
      throw new Error(`Updater metadata has an invalid file inventory: ${asset.name}`);
    }
    const updaterFiles = new Map();
    for (const entry of document.files) {
      const name = updaterPackageName(entry?.url, asset.name);
      if (!allowedPackages.has(name)) {
        throw new Error(
          `Updater references a package outside release inventory: ${name}`,
        );
      }
      const packageAsset = requireHostedAsset(assets, name);
      if (!Number.isSafeInteger(entry.size) || entry.size !== packageAsset.size) {
        throw new Error(`Updater package size does not match release inventory: ${name}`);
      }
      if (
        typeof entry.sha512 !== "string" ||
        !/^[A-Za-z0-9+/]{86}==$/.test(entry.sha512)
      ) {
        throw new Error(`Updater metadata has an invalid SHA-512 digest: ${name}`);
      }
      if (updaterFiles.has(name)) throw new Error(`Updater repeats package: ${name}`);
      updaterFiles.set(name, entry.sha512);
    }
    const primaryName = updaterPackageName(document.path, asset.name);
    if (
      !updaterFiles.has(primaryName) ||
      document.sha512 !== updaterFiles.get(primaryName)
    ) {
      throw new Error(
        `Updater primary package does not match file inventory: ${primaryName}`,
      );
    }
  }

  for (const asset of release.assets) {
    if (!expectedNames.has(asset.name)) {
      throw new Error(`Unexpected release asset: ${asset.name}`);
    }
  }

  return {
    version: contract.version,
    assetCount: release.assets.length,
    runtimeResults,
    checksumFiles: checksumAssets.map((asset) => asset.name),
  };
}

function runGh(args, encoding = "utf8") {
  return new Promise((resolve, reject) => {
    execFile(
      "gh",
      args,
      { encoding, maxBuffer: MAX_METADATA_SIZE, windowsHide: true },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new Error(`gh ${args[0]} failed: ${String(stderr || error.message).trim()}`),
          );
        } else {
          resolve(stdout);
        }
      },
    );
  });
}

export function selectDraftRelease(response, releaseTag) {
  if (!Array.isArray(response)) {
    throw new Error("GitHub releases response must be an array");
  }
  let releases;
  if (response.every(Array.isArray)) releases = response.flat();
  else if (response.every((item) => !Array.isArray(item))) releases = response;
  else throw new Error("GitHub releases response has mixed page shapes");
  const matches = releases.filter(
    (release) => release?.tag_name === releaseTag && release?.draft === true,
  );
  if (matches.length === 0) {
    throw new Error(`GitHub draft release is missing: ${releaseTag}`);
  }
  if (matches.length > 1) {
    throw new Error(`GitHub returned duplicate releases for tag: ${releaseTag}`);
  }
  return matches[0];
}

export async function verifyRemoteDraftRelease({
  releaseTag,
  repo,
  contractPath,
  expectedCommit = process.env.GITHUB_SHA,
  ghRunner = runGh,
}) {
  if (typeof releaseTag !== "string" || releaseTag.trim() === "") {
    throw new Error("Release tag is required");
  }
  if (typeof repo !== "string" || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) {
    throw new Error("Repository must use owner/repo format");
  }
  const resolvedContract = path.resolve(
    contractPath ?? "electron/fixtures/hypergen-release-contract.json",
  );
  const contract = JSON.parse(await readFile(resolvedContract, "utf8"));
  if (contract.tag && releaseTag !== contract.tag) {
    throw new Error(`Release tag does not match contract: ${releaseTag}`);
  }
  const releaseSource = await ghRunner([
    "api",
    "--paginate",
    "--slurp",
    `repos/${repo}/releases?per_page=100`,
  ]);
  const release = selectDraftRelease(JSON.parse(releaseSource), releaseTag);
  if (typeof release.name === "string" && !/HyperGen/.test(release.name)) {
    throw new Error("GitHub release title does not reference HyperGen");
  }
  let resolvedCommit;
  if (expectedCommit) {
    const commitSource = await ghRunner([
      "api",
      `repos/${repo}/commits/${encodeURIComponent(releaseTag)}`,
    ]);
    resolvedCommit = JSON.parse(commitSource).sha;
    if (typeof resolvedCommit !== "string" || resolvedCommit.trim() === "") {
      throw new Error(`Could not resolve release tag commit: ${releaseTag}`);
    }
  }

  return verifyHostedReleaseSnapshot({
    release,
    contract,
    expectedCommit,
    resolvedCommit,
    loadAsset: async (asset) =>
      ghRunner(
        [
          "api",
          "-H",
          "Accept: application/octet-stream",
          `repos/${repo}/releases/assets/${asset.id}`,
        ],
        null,
      ),
  });
}

export async function verifyReleaseArtifacts({ artifactsDir, contractPath }) {
  if (!artifactsDir || !contractPath) {
    throw new Error("Artifacts directory and release contract are required");
  }
  const root = path.resolve(artifactsDir);
  const contract = JSON.parse(await readFile(path.resolve(contractPath), "utf8"));
  if (
    !contract ||
    typeof contract !== "object" ||
    !contract.version ||
    !contract.platforms
  ) {
    throw new Error("Invalid release contract");
  }

  const files = await walkFiles(root);
  const index = indexByBasename(files);
  const requiredFiles = [];
  const updaterFiles = [];
  const runtimeResults = [];

  for (const platform of Object.values(contract.platforms)) {
    if (!Array.isArray(platform.packages))
      throw new Error("Invalid platform package inventory");
    for (const packageName of platform.packages) {
      if (/LTX Desktop|Lightricks/i.test(packageName)) {
        throw new Error(
          `Release contract contains legacy product branding: ${packageName}`,
        );
      }
      const filePath = requireUnique(index, packageName);
      requiredFiles.push(filePath);
      if (/^latest(?:-linux|-mac)?\.yml$/.test(packageName)) updaterFiles.push(filePath);
    }

    if (platform.runtimePrefix) {
      const manifestPath = requireUnique(
        index,
        `${platform.runtimePrefix}.manifest.json`,
      );
      const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
      const partsDirectory = path.dirname(manifestPath);
      await verifyRuntimeArchiveFile({
        manifestPath,
        partsDirectory,
        expectedChecksum: manifest.sha256,
      });
      requiredFiles.push(manifestPath);
      for (const part of manifest.parts ?? []) {
        requiredFiles.push(requireUnique(index, part.name));
      }
      runtimeResults.push({ prefix: platform.runtimePrefix, sha256: manifest.sha256 });
    }
  }

  const dependencyHashPath = requireUnique(index, "python-deps-hash.txt");
  const dependencyHash = (await readFile(dependencyHashPath, "utf8")).trim();
  if (!SHA256_PATTERN.test(dependencyHash)) {
    throw new Error("python-deps-hash.txt does not contain a SHA-256 checksum");
  }
  requiredFiles.push(dependencyHashPath);

  const checksumFiles = files.filter((filePath) =>
    /(?:^|\.)SHA256SUMS$/.test(path.basename(filePath)),
  );
  await verifyChecksumFiles(checksumFiles, files, requiredFiles);
  for (const updaterPath of updaterFiles) {
    await verifyLocalUpdaterMetadata({
      metadataPath: updaterPath,
      packagesDirectory: path.dirname(updaterPath),
      expectedVersion: contract.version,
    });
  }

  return {
    version: contract.version,
    assetCount: requiredFiles.length + checksumFiles.length,
    runtimeResults,
    checksumFiles: checksumFiles.map((filePath) => path.basename(filePath)),
  };
}

const isMain =
  process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  try {
    const options = parseArguments(process.argv.slice(2));
    if (options.help) {
      process.stdout.write(usage());
    } else if (
      options.updaterMetadata ||
      options.packagesDirectory ||
      options.expectedVersion
    ) {
      if (!options.updaterMetadata) {
        throw new Error("--updater-metadata is required for updater verification");
      }
      const result = await verifyLocalUpdaterMetadata({
        metadataPath: options.updaterMetadata,
        packagesDirectory: options.packagesDirectory,
        expectedVersion: options.expectedVersion,
      });
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    } else if (options.manifestPath) {
      const result = await verifyRuntimeArchiveFile({
        manifestPath: path.resolve(options.manifestPath),
        partsDirectory: path.resolve(
          options.partsDirectory ?? path.dirname(options.manifestPath),
        ),
        expectedChecksum: options.expectedChecksum,
      });
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    } else if (options.releaseTag || options.repo || options.expectedCommit) {
      if (!options.releaseTag || !options.repo) {
        throw new Error("--release-tag and --repo must be used together");
      }
      const result = await verifyRemoteDraftRelease({
        releaseTag: options.releaseTag,
        repo: options.repo,
        contractPath:
          options.contractPath ?? "electron/fixtures/hypergen-release-contract.json",
        expectedCommit: options.expectedCommit ?? process.env.GITHUB_SHA,
      });
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    } else {
      const result = await verifyReleaseArtifacts({
        artifactsDir: options.artifactsDir ?? "release-assets",
        contractPath:
          options.contractPath ?? "electron/fixtures/hypergen-release-contract.json",
      });
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    }
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
