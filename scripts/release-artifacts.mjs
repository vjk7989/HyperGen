import { constants as bufferConstants } from "node:buffer";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, open, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const PART_SUFFIX_PATTERN = /\.part(\d{3,})$/;

function assertNonEmptyString(value, label) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(`${label} must be a non-empty string`);
  }
}

function assertSha256(value, label) {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value.toLowerCase())) {
    throw new Error(`${label} must be a 64-character SHA-256 checksum`);
  }
}

async function sha256File(filePath) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filePath)) hash.update(chunk);
  return hash.digest("hex");
}

async function writeFully(handle, chunk) {
  let offset = 0;
  while (offset < chunk.length) {
    const { bytesWritten } = await handle.write(chunk, offset);
    if (bytesWritten <= 0) throw new Error("Failed to write release artifact");
    offset += bytesWritten;
  }
}

/**
 * Compute an order-independent hash of dependency file names and contents.
 * Basenames are used deliberately so the result is stable across runner paths.
 */
export async function computeDependencyHash(paths) {
  if (!Array.isArray(paths) || paths.length === 0) {
    throw new TypeError("Dependency paths must be a non-empty array");
  }

  const entries = [];
  const names = new Set();
  for (const filePath of paths) {
    assertNonEmptyString(filePath, "Dependency path");
    const info = await stat(filePath);
    if (!info.isFile()) throw new Error(`Dependency path is not a file: ${filePath}`);
    const name = path.basename(filePath);
    if (names.has(name)) {
      throw new Error(`Dependency file names must be unique: ${name}`);
    }
    names.add(name);
    entries.push({ name, size: info.size, sha256: await sha256File(filePath) });
  }

  entries.sort((left, right) => left.name.localeCompare(right.name, "en"));
  const hash = createHash("sha256");
  for (const entry of entries) {
    hash.update(`${entry.name}\0${entry.size}\0${entry.sha256}\n`, "utf8");
  }
  return hash.digest("hex");
}

function validateSplitDestination({ outputDir, prefix, partSize }) {
  assertNonEmptyString(outputDir, "Output directory");
  assertNonEmptyString(prefix, "Archive prefix");
  if (path.basename(prefix) !== prefix || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(prefix)) {
    throw new Error("Archive prefix must be a safe file name");
  }
  if (!Number.isSafeInteger(partSize) || partSize <= 0) {
    throw new RangeError("Part size must be a positive integer");
  }
}

async function removeOldSplitArtifacts(outputDir, prefix) {
  await mkdir(outputDir, { recursive: true });
  const stalePattern = new RegExp(
    `^${prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.part\\d+$`,
  );
  const staleNames = (await readdir(outputDir)).filter(
    (name) =>
      stalePattern.test(name) ||
      name === `${prefix}.manifest.json` ||
      name === "SHA256SUMS",
  );
  await Promise.all(
    staleNames.map((name) => rm(path.join(outputDir, name), { force: true })),
  );
}

/** Split an archive byte stream without materializing the complete archive on disk. */
export async function splitArchiveStream({ readable, outputDir, prefix, partSize }) {
  validateSplitDestination({ outputDir, prefix, partSize });
  if (!readable || typeof readable[Symbol.asyncIterator] !== "function") {
    throw new TypeError("Archive stream must be an async iterable");
  }
  await removeOldSplitArtifacts(outputDir, prefix);

  const totalHash = createHash("sha256");
  const parts = [];
  const createdPaths = [];
  let totalSize = 0;
  let partHandle;
  let partHash;
  let partBytes = 0;
  let partName;

  const finishPart = async () => {
    if (!partHandle) return;
    await partHandle.close();
    partHandle = undefined;
    parts.push({ name: partName, size: partBytes, sha256: partHash.digest("hex") });
    partBytes = 0;
  };

  try {
    for await (const value of readable) {
      const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
      if (chunk.length === 0) continue;
      totalHash.update(chunk);
      totalSize += chunk.length;
      let offset = 0;
      while (offset < chunk.length) {
        if (!partHandle) {
          partName = `${prefix}.part${String(parts.length + 1).padStart(3, "0")}`;
          const partPath = path.join(outputDir, partName);
          createdPaths.push(partPath);
          partHandle = await open(partPath, "w");
          partHash = createHash("sha256");
        }
        const length = Math.min(partSize - partBytes, chunk.length - offset);
        const slice = chunk.subarray(offset, offset + length);
        await writeFully(partHandle, slice);
        partHash.update(slice);
        partBytes += length;
        offset += length;
        if (partBytes === partSize) await finishPart();
      }
    }
    await finishPart();
    if (totalSize === 0) throw new Error("Runtime archive must not be empty");

    const manifest = {
      version: 1,
      archive: `${prefix}.tar.gz`,
      totalSize,
      sha256: totalHash.digest("hex"),
      parts,
    };
    const manifestPath = path.join(outputDir, `${prefix}.manifest.json`);
    await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    createdPaths.push(manifestPath);

    const checksumEntries = [
      ...parts.map((part) => `${part.sha256}  ${part.name}`),
      `${await sha256File(manifestPath)}  ${path.basename(manifestPath)}`,
    ];
    const checksumPath = path.join(outputDir, "SHA256SUMS");
    await writeFile(checksumPath, `${checksumEntries.join("\n")}\n`, "utf8");
    createdPaths.push(checksumPath);
    return { manifestPath, checksumPath, manifest };
  } catch (error) {
    if (partHandle) await partHandle.close().catch(() => {});
    await Promise.all(createdPaths.map((filePath) => rm(filePath, { force: true })));
    throw error;
  }
}

/** Split an existing archive into deterministic, sequential parts. */
export async function splitArchive(options) {
  const { archivePath, outputDir, prefix, partSize } = options;
  assertNonEmptyString(archivePath, "Archive path");
  validateSplitDestination({ outputDir, prefix, partSize });
  const archiveInfo = await stat(archivePath);
  if (!archiveInfo.isFile()) {
    throw new Error(`Archive path is not a file: ${archivePath}`);
  }
  if (archiveInfo.size === 0) throw new Error("Runtime archive must not be empty");
  const result = await splitArchiveStream({
    readable: createReadStream(archivePath),
    outputDir,
    prefix,
    partSize,
  });
  if (result.manifest.totalSize !== archiveInfo.size) {
    throw new Error("Runtime archive changed while it was being split");
  }
  return result;
}

function validateManifest(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Runtime manifest must be an object");
  }
  const manifest = value;
  if (!Number.isSafeInteger(manifest.totalSize) || manifest.totalSize <= 0) {
    throw new Error("Runtime manifest total size must be a positive integer");
  }
  assertSha256(manifest.sha256, "Runtime manifest checksum");
  if (!Array.isArray(manifest.parts) || manifest.parts.length === 0) {
    throw new Error("Runtime manifest must contain at least one part");
  }

  const names = new Set();
  manifest.parts.forEach((part, index) => {
    if (!part || typeof part !== "object") throw new Error("Invalid runtime part entry");
    assertNonEmptyString(part.name, "Runtime part name");
    if (path.basename(part.name) !== part.name) {
      throw new Error(`Unsafe runtime part name: ${part.name}`);
    }
    const suffix = PART_SUFFIX_PATTERN.exec(part.name);
    if (!suffix || Number(suffix[1]) !== index + 1) {
      throw new Error(`Runtime parts must be sequential: ${part.name}`);
    }
    if (names.has(part.name)) throw new Error(`Duplicate runtime part: ${part.name}`);
    names.add(part.name);
    if (!Number.isSafeInteger(part.size) || part.size <= 0) {
      throw new Error(`Runtime part size must be positive: ${part.name}`);
    }
    assertSha256(part.sha256, `Runtime part checksum for ${part.name}`);
  });
  return manifest;
}

async function verifyRuntimeArchiveInternal({
  manifestPath,
  partsDirectory,
  expectedChecksum,
  reconstructedPath,
  collect,
}) {
  assertNonEmptyString(manifestPath, "Manifest path");
  assertNonEmptyString(partsDirectory, "Parts directory");
  if (expectedChecksum !== undefined) {
    assertSha256(expectedChecksum, "Expected checksum");
    expectedChecksum = expectedChecksum.toLowerCase();
  }
  const manifest = validateManifest(JSON.parse(await readFile(manifestPath, "utf8")));
  const totalHash = createHash("sha256");
  const chunks = [];
  let totalSize = 0;
  let outputHandle;

  if (collect && manifest.totalSize > bufferConstants.MAX_LENGTH) {
    throw new Error("Runtime archive is too large to return as a Buffer");
  }

  try {
    if (reconstructedPath) {
      await mkdir(path.dirname(reconstructedPath), { recursive: true });
      outputHandle = await open(reconstructedPath, "w");
    }
    for (const part of manifest.parts) {
      const partPath = path.resolve(partsDirectory, part.name);
      if (path.dirname(partPath) !== path.resolve(partsDirectory)) {
        throw new Error(`Unsafe runtime part path: ${part.name}`);
      }
      const info = await stat(partPath);
      if (!info.isFile() || info.size !== part.size) {
        throw new Error(`Runtime part size integrity check failed: ${part.name}`);
      }
      const partHash = createHash("sha256");
      for await (const chunk of createReadStream(partPath)) {
        partHash.update(chunk);
        totalHash.update(chunk);
        totalSize += chunk.length;
        if (collect) chunks.push(chunk);
        if (outputHandle) await writeFully(outputHandle, chunk);
      }
      if (partHash.digest("hex") !== part.sha256.toLowerCase()) {
        throw new Error(`Runtime part checksum integrity check failed: ${part.name}`);
      }
    }
  } catch (error) {
    if (outputHandle) await outputHandle.close().catch(() => {});
    if (reconstructedPath) await rm(reconstructedPath, { force: true });
    throw error;
  }
  if (outputHandle) await outputHandle.close();

  const checksum = totalHash.digest("hex");
  if (totalSize !== manifest.totalSize) {
    if (reconstructedPath) await rm(reconstructedPath, { force: true });
    throw new Error("Runtime archive total size integrity check failed");
  }
  if (checksum !== manifest.sha256.toLowerCase()) {
    if (reconstructedPath) await rm(reconstructedPath, { force: true });
    throw new Error("Runtime archive checksum integrity check failed");
  }
  if (expectedChecksum && checksum !== expectedChecksum) {
    if (reconstructedPath) await rm(reconstructedPath, { force: true });
    throw new Error("Runtime archive does not match the expected checksum");
  }
  return {
    buffer: collect ? Buffer.concat(chunks, totalSize) : undefined,
    checksum,
    totalSize,
  };
}

/** Reconstruct and verify a split runtime archive. */
export async function verifyRuntimeArchive(options) {
  return (await verifyRuntimeArchiveInternal({ ...options, collect: true })).buffer;
}

/** Verify a runtime using streaming I/O, optionally writing its reconstruction. */
export async function verifyRuntimeArchiveFile(options) {
  return verifyRuntimeArchiveInternal({ ...options, collect: false });
}

export async function computeFileSha256(filePath) {
  return sha256File(filePath);
}
