import { spawn } from "node:child_process";
import { access, mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { computeDependencyHash, splitArchiveStream } from "./release-artifacts.mjs";

const DEFAULT_PART_SIZE = 1900 * 1024 * 1024;

function usage() {
  return `Usage: node scripts/package-python-runtime.mjs [options]

Options:
  --source <dir>          Runtime directory (default: python-embed)
  --output-dir <dir>      Artifact directory (default: release/runtime)
  --prefix <name>         Asset prefix (default is derived from the host platform)
  --part-size <bytes>     Maximum part size (default: ${DEFAULT_PART_SIZE})
  --dependency <file>     Dependency input; repeat as needed
  --hash-output <file>    Dependency hash output (default: python-deps-hash.txt)
  --help                  Show this help
`;
}

function parseArguments(argv) {
  const options = { dependencies: [] };
  const valueOptions = new Set([
    "--source",
    "--output-dir",
    "--prefix",
    "--part-size",
    "--dependency",
    "--hash-output",
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help") return { help: true };
    if (!valueOptions.has(flag)) throw new Error(`Unknown option: ${flag}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${flag}`);
    index += 1;
    if (flag === "--dependency") options.dependencies.push(value);
    else if (flag === "--source") options.source = value;
    else if (flag === "--output-dir") options.outputDir = value;
    else if (flag === "--prefix") options.prefix = value;
    else if (flag === "--part-size") options.partSize = Number(value);
    else if (flag === "--hash-output") options.hashOutput = value;
  }
  return options;
}

function defaultPrefix() {
  if (process.platform === "win32") return "python-embed-win32";
  if (process.platform === "linux" && process.arch === "x64") {
    return "python-embed-linux-x64";
  }
  return `python-embed-${process.platform}-${process.arch}`;
}

async function removeGeneratedParts(outputDir, prefix) {
  const escapedPrefix = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(
    `^(?:${escapedPrefix}(?:\\.part\\d+|\\.manifest\\.json)|SHA256SUMS)$`,
  );
  const names = await readdir(outputDir).catch(() => []);
  await Promise.all(
    names
      .filter((name) => pattern.test(name))
      .map((name) => rm(path.join(outputDir, name), { force: true })),
  );
}

async function streamTarToParts({ source, outputDir, prefix, partSize }) {
  const child = spawn("tar", ["-czf", "-", "-C", path.dirname(source), "python-embed"], {
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    if (stderr.length < 16_384) stderr += chunk;
  });
  const completion = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => {
      if (code === 0) resolve();
      else {
        reject(
          new Error(
            `tar failed with ${signal ? `signal ${signal}` : `exit code ${code}`}${stderr.trim() ? `: ${stderr.trim()}` : ""}`,
          ),
        );
      }
    });
  });
  const split = splitArchiveStream({
    readable: child.stdout,
    outputDir,
    prefix,
    partSize,
  }).catch((error) => {
    child.kill();
    throw error;
  });
  const [splitResult, completionResult] = await Promise.allSettled([split, completion]);
  if (splitResult.status === "rejected" || completionResult.status === "rejected") {
    child.kill();
    await removeGeneratedParts(outputDir, prefix);
    throw splitResult.status === "rejected"
      ? splitResult.reason
      : completionResult.reason;
  }
  return splitResult.value;
}

export async function packagePythonRuntime(rawOptions = {}) {
  const root = process.cwd();
  const source = path.resolve(root, rawOptions.source ?? "python-embed");
  const outputDir = path.resolve(
    root,
    rawOptions.outputDir ?? path.join("release", "runtime"),
  );
  const prefix = rawOptions.prefix ?? defaultPrefix();
  const partSize = rawOptions.partSize ?? DEFAULT_PART_SIZE;
  const hashOutput = path.resolve(root, rawOptions.hashOutput ?? "python-deps-hash.txt");
  const dependencies = (
    rawOptions.dependencies?.length
      ? rawOptions.dependencies
      : ["backend/uv.lock", "backend/pyproject.toml"]
  ).map((filePath) => path.resolve(root, filePath));

  const sourceInfo = await stat(source);
  if (!sourceInfo.isDirectory())
    throw new Error(`Python runtime source is not a directory: ${source}`);
  if (path.basename(source) !== "python-embed") {
    throw new Error("Python runtime source directory must be named python-embed");
  }
  await Promise.all(dependencies.map((filePath) => access(filePath)));
  await mkdir(outputDir, { recursive: true });
  await mkdir(path.dirname(hashOutput), { recursive: true });

  const split = await streamTarToParts({ source, outputDir, prefix, partSize });
  const dependencyHash = await computeDependencyHash(dependencies);
  await writeFile(hashOutput, `${dependencyHash}\n`, "utf8");

  return { dependencyHash, hashOutput, ...split };
}

const isMain =
  process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  try {
    const options = parseArguments(process.argv.slice(2));
    if (options.help) {
      process.stdout.write(usage());
    } else {
      const result = await packagePythonRuntime(options);
      process.stdout.write(
        `${JSON.stringify(
          {
            manifest: result.manifestPath,
            checksums: result.checksumPath,
            dependencyHash: result.dependencyHash,
            partCount: result.manifest.parts.length,
          },
          null,
          2,
        )}\n`,
      );
    }
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
