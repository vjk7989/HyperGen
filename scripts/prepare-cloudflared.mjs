import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const CLOUDFLARED_VERSION = "2026.10.0";
export const CLOUDFLARED_ARTIFACTS = Object.freeze({
  "win32-x64": {
    asset: "cloudflared-windows-amd64.exe",
    sha256: "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c",
    executable: "cloudflared.exe",
  },
  "linux-x64": {
    asset: "cloudflared-linux-amd64",
    sha256: "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db",
    executable: "cloudflared",
  },
  "darwin-arm64": {
    asset: "cloudflared-darwin-arm64.tgz",
    sha256: "a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70",
    executable: "cloudflared",
    archive: true,
  },
});

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");

function artifactFor(platform, arch) {
  const artifact = CLOUDFLARED_ARTIFACTS[`${platform}-${arch}`];
  if (!artifact) throw new Error(`Unsupported cloudflared target: ${platform}-${arch}`);
  return artifact;
}

async function download(url) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok)
    throw new Error(`cloudflared download failed: HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

export async function prepareCloudflared({
  platform = process.platform,
  arch = process.arch,
} = {}) {
  const artifact = artifactFor(platform, arch);
  const url = `https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/${artifact.asset}`;
  const bytes = await download(url);
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== artifact.sha256) {
    throw new Error(
      `cloudflared checksum mismatch: expected ${artifact.sha256}, got ${actual}`,
    );
  }

  const outputDir = path.join(repoRoot, "resources", "cloudflared");
  await mkdir(outputDir, { recursive: true });
  const downloadPath = path.join(outputDir, artifact.asset);
  const executablePath = path.join(outputDir, artifact.executable);
  await rm(executablePath, { force: true });
  await writeFile(downloadPath, bytes);
  if (artifact.archive) {
    execFileSync("tar", ["-xzf", downloadPath, "-C", outputDir], { stdio: "inherit" });
    await rm(downloadPath, { force: true });
  } else if (downloadPath !== executablePath) {
    await rename(downloadPath, executablePath);
  }
  if (platform !== "win32") await chmod(executablePath, 0o755);

  const verified = createHash("sha256")
    .update(await readFile(executablePath))
    .digest("hex");
  console.log(
    `Prepared cloudflared ${CLOUDFLARED_VERSION} for ${platform}-${arch}: ${executablePath}`,
  );
  return { executablePath, downloadSha256: actual, executableSha256: verified, url };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await prepareCloudflared();
}
