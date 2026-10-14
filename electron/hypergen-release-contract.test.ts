import { load as loadYaml } from "js-yaml";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, it } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

interface ReleaseContract {
  version: string;
  tag: string;
  workflow: string;
  platforms: Record<
    string,
    {
      runner?: string;
      runnerPattern?: string;
      arch: string;
      packages: string[];
      runtimePrefix?: string;
    }
  >;
  sharedArtifacts: string[];
}

interface WorkflowJob {
  name?: string;
  needs?: string | string[];
  "runs-on"?: string;
  steps?: Array<{
    name?: string;
    run?: string;
    uses?: string;
    with?: Record<string, unknown>;
    env?: Record<string, unknown>;
  }>;
  env?: Record<string, unknown>;
}

interface ReleaseWorkflow {
  on?: Record<string, unknown>;
  permissions?: Record<string, unknown>;
  jobs?: Record<string, WorkflowJob>;
}

interface BuilderConfiguration {
  appId?: string;
  productName?: string;
  detectUpdateChannel?: boolean;
  publish?: { provider?: string; owner?: string; repo?: string; channel?: string };
  win?: {
    artifactName?: string;
    target?: Array<{ target?: string; arch?: string[] }>;
  };
  linux?: { artifactName?: string; target?: string[] };
  mac?: {
    artifactName?: string;
    target?: Array<{ target?: string; arch?: string[] }>;
  };
}

interface RuntimeManifest {
  parts: Array<{ name: string; size: number; sha256?: string }>;
  totalSize: number;
  sha256?: string;
}

interface ReleaseArtifactTools {
  computeDependencyHash(paths: string[]): Promise<string>;
  splitArchive(options: {
    archivePath: string;
    outputDir: string;
    prefix: string;
    partSize: number;
  }): Promise<{ manifestPath: string; checksumPath: string; manifest: RuntimeManifest }>;
  verifyRuntimeArchive(options: {
    manifestPath: string;
    partsDirectory: string;
    expectedChecksum?: string;
  }): Promise<Buffer>;
}

interface HostedReleaseVerifier {
  selectDraftRelease<T extends { tag_name?: string; draft?: boolean }>(
    releases: T[],
    releaseTag: string,
  ): T;
  verifyHostedReleaseSnapshot(options: {
    release: {
      draft: boolean;
      prerelease?: boolean;
      target_commitish?: string;
      assets: Array<{
        id: number;
        name: string;
        size: number;
        state: string;
        digest: string;
      }>;
    };
    contract: { version: string; platforms: Record<string, { packages: string[] }> };
    loadAsset(asset: { name: string }): Promise<Buffer>;
    expectedCommit?: string;
    resolvedCommit?: string;
  }): Promise<unknown>;
  verifyReleaseArtifacts(options: {
    artifactsDir: string;
    contractPath: string;
  }): Promise<unknown>;
}

interface RuntimePackager {
  packagePythonRuntime(options: {
    source: string;
    outputDir: string;
    prefix: string;
    partSize: number;
    dependencies: string[];
    hashOutput: string;
  }): Promise<{ manifestPath: string; manifest: RuntimeManifest }>;
}

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const contractPath = path.join(here, "fixtures", "hypergen-release-contract.json");
const toolsUrl = pathToFileURL(path.join(root, "scripts", "release-artifacts.mjs")).href;
const verifierUrl = pathToFileURL(
  path.join(root, "scripts", "verify-release-artifacts.mjs"),
).href;
const packagerUrl = pathToFileURL(
  path.join(root, "scripts", "package-python-runtime.mjs"),
).href;
const tempDirs: string[] = [];

async function contract(): Promise<ReleaseContract> {
  return JSON.parse(await readFile(contractPath, "utf8")) as ReleaseContract;
}

async function workflowSource(): Promise<string> {
  const spec = await contract();
  return readFile(path.join(root, spec.workflow), "utf8");
}

async function workflow(): Promise<ReleaseWorkflow> {
  return loadYaml(await workflowSource()) as ReleaseWorkflow;
}

async function artifactTools(): Promise<ReleaseArtifactTools> {
  return import(toolsUrl) as Promise<ReleaseArtifactTools>;
}

async function hostedReleaseVerifier(): Promise<HostedReleaseVerifier> {
  return import(verifierUrl) as Promise<HostedReleaseVerifier>;
}

async function runtimePackager(): Promise<RuntimePackager> {
  return import(packagerUrl) as Promise<RuntimePackager>;
}

function sha256(content: string | Buffer): string {
  return createHash("sha256").update(content).digest("hex");
}

function sha512(content: string | Buffer): string {
  return createHash("sha512").update(content).digest("base64");
}

function jobCommands(job: WorkflowJob): string {
  return (job.steps ?? []).map((step) => step.run ?? "").join("\n");
}

function needs(job: WorkflowJob): string[] {
  if (Array.isArray(job.needs)) return job.needs;
  return job.needs ? [job.needs] : [];
}

function findStep(
  job: WorkflowJob,
  name: RegExp,
): NonNullable<WorkflowJob["steps"]>[number] {
  const step = job.steps?.find((candidate) => name.test(candidate.name ?? ""));
  assert.ok(step, `missing workflow step matching ${name}`);
  return step;
}

function stepIndex(job: WorkflowJob, name: RegExp): number {
  const index =
    job.steps?.findIndex((candidate) => name.test(candidate.name ?? "")) ?? -1;
  assert.notEqual(index, -1, `missing workflow step matching ${name}`);
  return index;
}

function workflowDispatchInput(doc: ReleaseWorkflow, name: string): unknown {
  const dispatch = doc.on?.workflow_dispatch as
    | { inputs?: Record<string, unknown> }
    | undefined;
  return dispatch?.inputs?.[name];
}

async function makeTempDir(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "hypergen-release-test-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map((dir) => rm(dir, { force: true, recursive: true })),
  );
});

describe("HyperGen release workflow contract", () => {
  it("uses the approved preview version and a manually dispatchable release tag", async () => {
    const spec = await contract();
    const packageJson = JSON.parse(
      await readFile(path.join(root, "package.json"), "utf8"),
    ) as {
      version?: string;
    };
    assert.equal(packageJson.version, spec.version);

    const doc = await workflow();
    const versionInput = workflowDispatchInput(doc, "version") as
      | { default?: unknown; required?: unknown }
      | undefined;
    assert.equal(versionInput?.default, spec.version);
    assert.equal(versionInput?.required, true);
    assert.equal(
      (versionInput as { description?: unknown } | undefined)?.description,
      "Release version",
    );
  });

  it("declares HyperGen installer identity, native targets, and collision-safe filenames", async () => {
    const source = await readFile(path.join(root, "electron-builder.yml"), "utf8");
    const builder = loadYaml(source) as BuilderConfiguration;

    assert.equal(builder.appId, "io.github.vjk7989.hypergen");
    assert.equal(builder.productName, "HyperGen");
    assert.equal(builder.publish?.provider, "github");
    assert.equal(builder.publish?.owner, "vjk7989");
    assert.equal(builder.publish?.repo, "HyperGen");
    assert.equal(builder.publish?.channel, "latest");
    assert.equal(builder.detectUpdateChannel, false);
    assert.deepEqual(builder.win?.target, [{ target: "nsis", arch: ["x64"] }]);
    assert.deepEqual(builder.linux?.target, ["AppImage", "deb"]);
    assert.deepEqual(builder.mac?.target, [
      { target: "dmg", arch: ["arm64"] },
      { target: "zip", arch: ["arm64"] },
    ]);
    assert.match(builder.win?.artifactName ?? "", /\$\{version\}/);
    assert.match(builder.mac?.artifactName ?? "", /\$\{version\}/);
  });

  it("runs the complete quality gate before any native packaging job", async () => {
    const doc = await workflow();
    const jobs = doc.jobs ?? {};
    const quality = jobs.quality;
    assert.ok(quality, "release.yml must define a quality job");

    const commands = jobCommands(quality);
    for (const requiredCommand of [
      "pnpm format-check",
      "pnpm typecheck:ts",
      "pnpm typecheck:py",
      "pnpm lint",
      "pnpm branding:check",
      "pnpm scripts:test",
      "pnpm openapi:check",
      "pytest",
      "pnpm build:frontend",
    ]) {
      assert.match(
        commands,
        new RegExp(requiredCommand.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      );
    }
    assert.match(
      commands,
      /npm exec --yes --package=@nanonets\/graft@0\.21\.1 -- graft build/,
    );
    assert.match(
      commands,
      /npm exec --yes --package=@nanonets\/graft@0\.21\.1 -- graft check/,
    );

    for (const jobName of ["build-windows", "build-linux", "build-macos"]) {
      assert.ok(
        needs(jobs[jobName] ?? {}).includes("quality"),
        `${jobName} must need quality`,
      );
    }
  });

  it("uses the repository Python runtime pin in the quality job", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const setupPython = jobs.quality?.steps?.find((step) =>
      String(step.uses ?? "").startsWith("actions/setup-python@"),
    );
    assert.ok(setupPython, "quality job must set up Python");
    const pinnedVersion = (
      await readFile(path.join(root, "backend", ".python-version"), "utf8")
    ).trim();
    assert.equal(setupPython.with?.["python-version"], pinnedVersion);
  });

  it("builds every approved installer on its native runner and uploads updater metadata", async () => {
    const spec = await contract();
    const jobs = (await workflow()).jobs ?? {};
    const cases = [
      ["windows", "build-windows"],
      ["linux", "build-linux"],
      ["macos", "build-macos"],
    ] as const;

    for (const [platform, jobName] of cases) {
      const expected = spec.platforms[platform];
      const job = jobs[jobName];
      assert.ok(job, `missing ${jobName}`);
      if (expected.runner) assert.equal(job["runs-on"], expected.runner);
      if (expected.runnerPattern) {
        assert.match(String(job["runs-on"]), new RegExp(expected.runnerPattern));
      }

      const serialized = JSON.stringify(job);
      assert.match(serialized, new RegExp(`--${expected.arch}`));
      assert.match(serialized, /--publish(?:[ "]+)never/);
      for (const artifact of expected.packages) {
        assert.ok(serialized.includes(artifact), `${jobName} must upload ${artifact}`);
      }
    }
  });

  it("packages downloadable Windows and Linux runtimes with hash, manifest, parts, and checksums", async () => {
    const spec = await contract();
    const jobs = (await workflow()).jobs ?? {};

    for (const [platform, jobName] of [
      ["windows", "build-windows"],
      ["linux", "build-linux"],
    ] as const) {
      const expected = spec.platforms[platform];
      const serialized = JSON.stringify(jobs[jobName] ?? {});
      assert.ok(expected.runtimePrefix);
      assert.ok(serialized.includes("scripts/package-python-runtime.mjs"));
      assert.ok(serialized.includes(`${expected.runtimePrefix}.manifest.json`));
      assert.match(serialized, new RegExp(`${expected.runtimePrefix}[^"']*\\.part`));
      for (const artifact of spec.sharedArtifacts) {
        assert.ok(serialized.includes(artifact), `${jobName} must upload ${artifact}`);
      }
    }
  });

  it("hashes every dependency input that can change a packaged Python runtime", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const dependencyInputs = [
      "backend/.python-version",
      "backend/pyproject.toml",
      "backend/uv.lock",
      "scripts/prepare-python.ps1",
      "scripts/prepare-python.sh",
    ];

    for (const jobName of ["build-windows", "build-linux"]) {
      const packageStep = findStep(
        jobs[jobName] ?? {},
        /Package downloadable .* runtime/i,
      );
      const command = packageStep.run ?? "";
      for (const dependency of dependencyInputs) {
        assert.match(
          command,
          new RegExp(
            `--dependency\\s+${dependency.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`,
          ),
          `${jobName} must hash ${dependency}`,
        );
      }
    }
  });

  it("verifies streamed runtime parts before uploading and never uploads an unsplit archive", async () => {
    const jobs = (await workflow()).jobs ?? {};
    for (const [jobName, prefix] of [
      ["build-windows", "python-embed-win32"],
      ["build-linux", "python-embed-linux-x64"],
    ] as const) {
      const job = jobs[jobName] ?? {};
      const packageIndex = stepIndex(job, /Package downloadable .* runtime/i);
      const verifyIndex = stepIndex(job, /Verify .* runtime reconstruction/i);
      const uploadIndex = stepIndex(job, /Upload .* assets to the draft/i);
      assert.ok(packageIndex < verifyIndex && verifyIndex < uploadIndex);

      const verifyCommand = job.steps?.[verifyIndex]?.run ?? "";
      const uploadCommand = job.steps?.[uploadIndex]?.run ?? "";
      assert.ok(verifyCommand.includes(`${prefix}.manifest.json`));
      assert.ok(!uploadCommand.includes(`${prefix}.tar.gz`));
    }
  });

  it("frees the prepared runtime and checks disk capacity before Windows and Linux Electron packaging", async () => {
    const jobs = (await workflow()).jobs ?? {};
    for (const jobName of ["build-windows", "build-linux"]) {
      const job = jobs[jobName] ?? {};
      const verifyIndex = stepIndex(job, /Verify .* runtime reconstruction/i);
      const cleanupIndex = stepIndex(
        job,
        /Remove .*python.*runtime|Remove prepared .*runtime/i,
      );
      const diskIndex = stepIndex(job, /Check .*disk|Verify .*disk/i);
      const packageIndex = stepIndex(job, /Build .* package/i);
      assert.ok(verifyIndex < cleanupIndex && cleanupIndex < diskIndex);
      assert.ok(diskIndex < packageIndex);

      const cleanupCommand = job.steps?.[cleanupIndex]?.run ?? "";
      const diskCommand = job.steps?.[diskIndex]?.run ?? "";
      assert.match(cleanupCommand, /python-embed/);
      assert.match(diskCommand, /(?:free|available|FreeSpace)/i);
      assert.match(diskCommand, /(?:20\s*(?:GB|GiB)|21474836480|20971520)/i);
    }
  });

  it("keeps optional Windows Docker cleanup non-fatal while enforcing the disk guard", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const windows = jobs["build-windows"] ?? {};
    const cleanup = findStep(windows, /Reclaim unused Windows runner space/i).run ?? "";
    const diskGuard = findStep(windows, /Check Windows packaging disk budget/i).run ?? "";

    assert.match(cleanup, /docker system prune/i);
    const daemonAware =
      /docker info/i.test(cleanup) &&
      /LASTEXITCODE\s*-eq\s*0/i.test(cleanup) &&
      cleanup.indexOf("docker info") < cleanup.indexOf("docker system prune");
    const explicitlyNonFatal =
      /docker system prune[^\n]*(?:\|\|\s*(?:true|exit 0))/i.test(cleanup) ||
      /LASTEXITCODE\s*-ne\s*0[\s\S]*(?:Write-Warning|LASTEXITCODE\s*=\s*0)/i.test(
        cleanup,
      );
    assert.ok(
      daemonAware || explicitlyNonFatal,
      "Docker cleanup must tolerate an installed CLI with an unavailable daemon",
    );

    assert.match(diskGuard, /21474836480|20\s*GiB/i);
    assert.match(diskGuard, /(?:throw|exit\s+1)/i);
  });

  it("keeps setup-uv post actions valid after native runtime cache cleanup", async () => {
    const jobs = (await workflow()).jobs ?? {};
    for (const jobName of ["build-windows", "build-linux", "build-macos"]) {
      const job = jobs[jobName] ?? {};
      const setupUv = job.steps?.find((step) =>
        String(step.uses ?? "").startsWith("astral-sh/setup-uv@"),
      );
      if (setupUv?.with?.["enable-cache"] !== true) continue;

      const commands = jobCommands(job);
      if (commands.includes("uv cache clean")) {
        assert.equal(
          setupUv.with?.["prune-cache"],
          false,
          `${jobName} must disable setup-uv post-job pruning after deleting its cache schema`,
        );
      }
      let cleanIndex = commands.indexOf("uv cache clean");
      while (cleanIndex >= 0) {
        const afterward = commands.slice(cleanIndex + "uv cache clean".length);
        assert.match(
          afterward,
          /(?:New-Item[^\n]*(?:-ItemType\s+Directory|-Type\s+Directory)[^\n]*UV_CACHE_DIR|mkdir\s+-p[^\n]*UV_CACHE_DIR)/i,
          `${jobName} must recreate UV_CACHE_DIR after cleaning a cached uv installation`,
        );
        cleanIndex = commands.indexOf("uv cache clean", cleanIndex + 1);
      }
    }

    const qualitySetupUv = jobs.quality?.steps?.find((step) =>
      String(step.uses ?? "").startsWith("astral-sh/setup-uv@"),
    );
    assert.notEqual(
      qualitySetupUv?.with?.["prune-cache"],
      false,
      "quality job must keep normal setup-uv cache pruning",
    );
  });

  it("rejects every platform upload at the 2,000,000,000-byte boundary", async () => {
    const jobs = (await workflow()).jobs ?? {};
    for (const jobName of ["build-windows", "build-linux", "build-macos"]) {
      const upload = findStep(jobs[jobName] ?? {}, /Upload .* assets to the draft/i);
      const command = upload.run ?? "";
      assert.match(command, /(?:-ge|>=?)\s*2000000000/);
      assert.match(command, /Release asset exceeds GitHub's safe upload limit/);
    }
  });

  it("creates one draft only after every platform and publishes it only after verification", async () => {
    const doc = await workflow();
    const jobs = doc.jobs ?? {};
    const release = jobs.release;
    assert.ok(release, "release.yml must define a release job");
    assert.deepEqual(
      new Set(needs(release)),
      new Set(["quality", "build-windows", "build-linux", "build-macos"]),
    );
    assert.equal(doc.permissions?.contents, "write");

    const serialized = JSON.stringify(release);
    assert.ok(serialized.includes("scripts/verify-release-artifacts.mjs"));
    assert.match(serialized, /draft[^}]*true/i);
    assert.match(serialized, /gh release edit[^\n]*--draft=false/);

    const source = await workflowSource();
    assert.doesNotMatch(source, /git\s+push\s+[^\n]*(?:--tags|--mirror)/);
  });

  it("verifies the remote draft from GitHub metadata without downloading all assets", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const release = jobs.release ?? {};
    const verification = findStep(release, /Verify remote installer metadata/i);
    const command = verification.run ?? "";
    assert.match(command, /--release-tag\s+"?\$RELEASE_TAG"?/);
    assert.match(command, /--repo\s+"?\$GITHUB_REPOSITORY"?/);
    assert.doesNotMatch(command, /--artifacts-dir/);
    assert.ok(
      !(release.steps ?? []).some((step) =>
        String(step.uses ?? "").startsWith("actions/download-artifact@"),
      ),
    );
  });

  it("proves reused drafts and release tags resolve to the workflow commit", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const draftCommand = jobCommands(jobs.draft ?? {});
    const releaseCommand = jobCommands(jobs.release ?? {});

    assert.match(draftCommand, /GITHUB_SHA/);
    assert.match(draftCommand, /git rev-parse[^\n]*RELEASE_TAG[^\n]*\^\{commit\}/);
    assert.match(releaseCommand, /--expected-commit\s+"?\$GITHUB_SHA"?/);
    assert.match(releaseCommand, /git rev-parse[^\n]*RELEASE_TAG[^\n]*\^\{commit\}/);
    assert.match(releaseCommand, /GITHUB_SHA/);
    const remoteProof = releaseCommand.indexOf("--expected-commit");
    const tagProof = releaseCommand.indexOf("git rev-parse");
    const publish = releaseCommand.indexOf("gh release edit");
    assert.ok(remoteProof >= 0 && remoteProof < publish);
    assert.ok(tagProof >= 0 && tagProof < publish);
    assert.match(releaseCommand, /gh release edit[^\n]*--draft=false/);
  });

  it("creates and proves the exact remote tag before creating or reusing the draft", async () => {
    const jobs = (await workflow()).jobs ?? {};
    const command =
      findStep(jobs.draft ?? {}, /Create the single draft release/i).run ?? "";

    assert.match(
      command,
      /gh api --method POST "repos\/\$GITHUB_REPOSITORY\/git\/refs"\s*\\\s*-f ref="refs\/tags\/\$RELEASE_TAG"\s*\\\s*-f sha="\$GITHUB_SHA"/,
      "a missing release tag must be created on the remote at the workflow commit",
    );

    const createTag = command.indexOf(
      'gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs"',
    );
    const fetchCreatedTag = command.indexOf(
      'git fetch --force origin "refs/tags/$RELEASE_TAG:refs/tags/$RELEASE_TAG"',
      createTag,
    );
    const proveTag = command.indexOf(
      'test "$(git rev-parse "$RELEASE_TAG^{commit}")" = "$GITHUB_SHA"',
      fetchCreatedTag,
    );
    const inspectDraft = command.indexOf(
      'gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY"',
      proveTag,
    );
    const createDraft = command.indexOf('gh release create "$RELEASE_TAG"', proveTag);
    const reuseDraft = command.indexOf('gh release edit "$RELEASE_TAG"', proveTag);

    assert.ok(createTag >= 0, "missing exact remote tag creation");
    assert.ok(fetchCreatedTag > createTag, "created tag must be fetched from origin");
    assert.ok(proveTag > fetchCreatedTag, "fetched tag must resolve to GITHUB_SHA");
    assert.ok(inspectDraft > proveTag, "draft lookup must follow tag proof");
    assert.ok(createDraft > proveTag, "draft creation must follow tag proof");
    assert.ok(reuseDraft > proveTag, "draft reuse must follow tag proof");
  });

  it("uses an authenticated draft-capable exact-tag lookup in every release job", async () => {
    const jobs = (await workflow()).jobs ?? {};
    for (const jobName of [
      "draft",
      "build-windows",
      "build-linux",
      "build-macos",
      "release",
    ]) {
      const commands = jobCommands(jobs[jobName] ?? {});
      assert.doesNotMatch(commands, /releases\/tags\//);
      assert.match(
        commands,
        /gh release view[^\n]*\$RELEASE_TAG[^\n]*(?:--json|--jq)/,
        `${jobName} must inspect the authenticated draft by exact tag`,
      );
    }
  });

  it("keeps the preview release explicitly unsigned", async () => {
    const source = await workflowSource();
    const builder = await readFile(path.join(root, "electron-builder.yml"), "utf8");

    assert.match(source, /CSC_IDENTITY_AUTO_DISCOVERY:\s*["']?false["']?/);
    assert.doesNotMatch(
      source,
      /(APPLE_ID|APPLE_APP_SPECIFIC_PASSWORD|WIN_CSC_LINK|CSC_LINK)/,
    );
    assert.doesNotMatch(builder, /^\s*(identity|notarize):/m);
  });

  it("bundles the macOS runtime while keeping the preview updater on a supported channel", async () => {
    const source = await workflowSource();
    const builder = await readFile(path.join(root, "electron-builder.yml"), "utf8");
    const macJob = JSON.stringify((await workflow()).jobs?.["build-macos"] ?? {});

    assert.match(builder, /mac:[\s\S]*from:\s*python-embed[\s\S]*to:\s*python/);
    assert.match(macJob, /prepare-python\.sh/);
    assert.doesNotMatch(source, /channel:\s*preview/);
    assert.match(source, /prerelease[^\n}]*true/i);
  });
});

describe("HyperGen release artifact tools", () => {
  it("hashes dependency inputs deterministically and changes when their content changes", async () => {
    const dir = await makeTempDir();
    const uvLock = path.join(dir, "uv.lock");
    const project = path.join(dir, "pyproject.toml");
    await writeFile(uvLock, "version = 1\n");
    await writeFile(project, '[project]\nname = "hypergen"\n');
    const tools = await artifactTools();

    const first = await tools.computeDependencyHash([uvLock, project]);
    const reordered = await tools.computeDependencyHash([project, uvLock]);
    assert.match(first, /^[a-f0-9]{64}$/);
    assert.equal(first, reordered);

    await writeFile(uvLock, "version = 2\n");
    assert.notEqual(await tools.computeDependencyHash([uvLock, project]), first);
  });

  it("splits a runtime archive without empty parts and writes downloader-compatible metadata", async () => {
    const dir = await makeTempDir();
    const archivePath = path.join(dir, "python-embed-linux-x64.tar.gz");
    const payload = Buffer.from("0123456789abcdef");
    await writeFile(archivePath, payload);
    const tools = await artifactTools();

    const result = await tools.splitArchive({
      archivePath,
      outputDir: dir,
      prefix: "python-embed-linux-x64",
      partSize: 5,
    });

    assert.equal(result.manifest.totalSize, payload.length);
    assert.deepEqual(
      result.manifest.parts.map((part) => part.size),
      [5, 5, 5, 1],
    );
    assert.ok(
      result.manifest.parts.every((part) =>
        part.name.startsWith("python-embed-linux-x64."),
      ),
    );
    assert.ok(
      result.manifest.parts.every((part) => /^[a-f0-9]{64}$/.test(part.sha256 ?? "")),
    );
    assert.equal(
      result.manifest.sha256,
      createHash("sha256").update(payload).digest("hex"),
    );
    assert.equal(
      path.basename(result.manifestPath),
      "python-embed-linux-x64.manifest.json",
    );
    assert.equal(path.basename(result.checksumPath), "SHA256SUMS");
  });

  it("reconstructs an exact runtime archive and rejects a tampered part", async () => {
    const dir = await makeTempDir();
    const archivePath = path.join(dir, "python-embed-win32.tar.gz");
    const payload = Buffer.from("a-runtime-archive-with-an-uneven-final-part");
    await writeFile(archivePath, payload);
    const tools = await artifactTools();
    const split = await tools.splitArchive({
      archivePath,
      outputDir: dir,
      prefix: "python-embed-win32",
      partSize: 8,
    });

    const reconstructed = await tools.verifyRuntimeArchive({
      manifestPath: split.manifestPath,
      partsDirectory: dir,
      expectedChecksum: split.manifest.sha256,
    });
    assert.deepEqual(reconstructed, payload);

    const firstPart = path.join(dir, split.manifest.parts[0].name);
    await writeFile(firstPart, "tampered");
    await assert.rejects(
      tools.verifyRuntimeArchive({
        manifestPath: split.manifestPath,
        partsDirectory: dir,
        expectedChecksum: split.manifest.sha256,
      }),
      /checksum|size|integrity/i,
    );
  });

  it("rejects invalid split sizes before writing artifacts", async () => {
    const dir = await makeTempDir();
    const archivePath = path.join(dir, "runtime.tar.gz");
    await writeFile(archivePath, "runtime");
    const tools = await artifactTools();

    await assert.rejects(
      tools.splitArchive({ archivePath, outputDir: dir, prefix: "runtime", partSize: 0 }),
      /part size/i,
    );
  });

  it("selects one exact draft from a list-based GitHub release snapshot", async () => {
    const verifier = await hostedReleaseVerifier();
    const expected = {
      id: 2,
      tag_name: "v0.1.0-preview.1",
      draft: true,
      assets: [],
    };
    const selected = verifier.selectDraftRelease(
      [
        { id: 1, tag_name: "v0.0.9", draft: true, assets: [] },
        expected,
        { id: 3, tag_name: "v0.1.0-preview.1", draft: false, assets: [] },
      ],
      "v0.1.0-preview.1",
    );
    assert.equal(selected, expected);
  });

  it("rejects missing or duplicate exact-tag drafts from a release list", async () => {
    const verifier = await hostedReleaseVerifier();
    assert.throws(
      () =>
        verifier.selectDraftRelease(
          [
            { tag_name: "v0.1.0-preview.1", draft: false },
            { tag_name: "v0.0.9", draft: true },
          ],
          "v0.1.0-preview.1",
        ),
      /draft|missing|not found/i,
    );
    assert.throws(
      () =>
        verifier.selectDraftRelease(
          [
            { tag_name: "v0.1.0-preview.1", draft: true },
            { tag_name: "v0.1.0-preview.1", draft: true },
          ],
          "v0.1.0-preview.1",
        ),
      /duplicate|multiple|exactly one/i,
    );
  });

  it("streams a packaged runtime into bounded parts without retaining an unsplit archive", async () => {
    const dir = await makeTempDir();
    const source = path.join(dir, "python-embed");
    const outputDir = path.join(dir, "parts");
    const dependency = path.join(dir, "uv.lock");
    const hashOutput = path.join(dir, "python-deps-hash.txt");
    await mkdir(path.join(source, "Lib"), { recursive: true });
    await writeFile(path.join(source, "python.exe"), Buffer.alloc(37, 0x41));
    await writeFile(path.join(source, "Lib", "runtime.py"), Buffer.alloc(29, 0x42));
    await writeFile(dependency, "version = 1\n");
    const packager = await runtimePackager();

    const result = await packager.packagePythonRuntime({
      source,
      outputDir,
      prefix: "python-embed-test",
      partSize: 64,
      dependencies: [dependency],
      hashOutput,
    });

    const names = await readdir(outputDir);
    assert.ok(!names.includes("python-embed-test.tar.gz"));
    assert.ok(result.manifest.parts.length > 1);
    assert.ok(result.manifest.parts.every((part) => part.size <= 64));
    await assert.rejects(access(path.join(outputDir, "python-embed-test.tar.gz")));

    const tools = await artifactTools();
    await tools.verifyRuntimeArchive({
      manifestPath: result.manifestPath,
      partsDirectory: outputDir,
      expectedChecksum: result.manifest.sha256,
    });
  });

  it("binds local updater paths, file names, sizes, and sha512 values to package bytes", async () => {
    const dir = await makeTempDir();
    const packageName = "HyperGen-test.exe";
    const packageBytes = Buffer.from("signed-package-placeholder");
    const dependencyHash = `${"a".repeat(64)}\n`;
    const packagePath = path.join(dir, packageName);
    const updaterPath = path.join(dir, "latest.yml");
    const dependencyPath = path.join(dir, "python-deps-hash.txt");
    const checksumPath = path.join(dir, "windows-x64.SHA256SUMS");
    const contractFile = path.join(dir, "contract.json");
    await writeFile(packagePath, packageBytes);
    await writeFile(dependencyPath, dependencyHash);
    await writeFile(
      contractFile,
      JSON.stringify({
        version: "0.1.0-preview.1",
        platforms: { windows: { packages: [packageName, "latest.yml"] } },
      }),
    );
    const verifier = await hostedReleaseVerifier();

    const writeUpdater = async (overrides: {
      path?: string;
      fileUrl?: string;
      size?: number;
      digest?: string;
    }) => {
      const digest = overrides.digest ?? sha512(packageBytes);
      const updater = [
        "version: 0.1.0-preview.1",
        "files:",
        `  - url: ${overrides.fileUrl ?? packageName}`,
        `    sha512: ${digest}`,
        `    size: ${overrides.size ?? packageBytes.length}`,
        `path: ${overrides.path ?? packageName}`,
        `sha512: ${digest}`,
        "",
      ].join("\n");
      await writeFile(updaterPath, updater);
      await writeFile(
        checksumPath,
        [
          `${sha256(packageBytes)}  ${packageName}`,
          `${sha256(updater)}  latest.yml`,
          `${sha256(dependencyHash)}  python-deps-hash.txt`,
          "",
        ].join("\n"),
      );
    };

    await writeUpdater({});
    await verifier.verifyReleaseArtifacts({
      artifactsDir: dir,
      contractPath: contractFile,
    });

    for (const invalid of [
      { path: "Other.exe" },
      { fileUrl: "Other.exe" },
      { size: packageBytes.length + 1 },
      { digest: Buffer.alloc(64, 7).toString("base64") },
    ]) {
      await writeUpdater(invalid);
      await assert.rejects(
        verifier.verifyReleaseArtifacts({
          artifactsDir: dir,
          contractPath: contractFile,
        }),
        /updater|path|file|size|sha512|checksum/i,
      );
    }
  });

  it("accepts a hosted draft whose main target resolves through its tag to the workflow commit", async () => {
    const verifier = await hostedReleaseVerifier();
    const version = "0.1.0-preview.1";
    const dependencyHash = `${"a".repeat(64)}\n`;
    const packageSha512 = Buffer.alloc(64, 3).toString("base64");
    const updater = [
      `version: ${version}`,
      "files:",
      "  - url: HyperGen-test.exe",
      `    sha512: ${packageSha512}`,
      "    size: 1500000000",
      "path: HyperGen-test.exe",
      `sha512: ${packageSha512}`,
      "",
    ].join("\n");
    const packageDigest = "b".repeat(64);
    const updaterDigest = createHash("sha256").update(updater).digest("hex");
    const dependencyDigest = createHash("sha256").update(dependencyHash).digest("hex");
    const checksums = [
      `${packageDigest}  HyperGen-test.exe`,
      `${updaterDigest}  latest.yml`,
      `${dependencyDigest}  python-deps-hash.txt`,
      "",
    ].join("\n");
    const metadata = new Map<string, Buffer>([
      ["latest.yml", Buffer.from(updater)],
      ["python-deps-hash.txt", Buffer.from(dependencyHash)],
      ["windows-x64.SHA256SUMS", Buffer.from(checksums)],
    ]);
    const assets = [
      {
        id: 1,
        name: "HyperGen-test.exe",
        size: 1_500_000_000,
        state: "uploaded",
        digest: `sha256:${packageDigest}`,
      },
      ...[...metadata].map(([name, content], index) => ({
        id: index + 2,
        name,
        size: content.length,
        state: "uploaded",
        digest: `sha256:${createHash("sha256").update(content).digest("hex")}`,
      })),
    ];
    const loaded: string[] = [];

    await verifier.verifyHostedReleaseSnapshot({
      release: {
        draft: true,
        prerelease: true,
        target_commitish: "main",
        assets,
      },
      contract: {
        version,
        platforms: { windows: { packages: ["HyperGen-test.exe", "latest.yml"] } },
      },
      loadAsset: async (asset) => {
        loaded.push(asset.name);
        const content = metadata.get(asset.name);
        assert.ok(content, `large asset must not be downloaded: ${asset.name}`);
        return content;
      },
      expectedCommit: "1".repeat(40),
      resolvedCommit: "1".repeat(40),
    });

    assert.deepEqual(loaded.sort(), [
      "latest.yml",
      "python-deps-hash.txt",
      "windows-x64.SHA256SUMS",
    ]);
  });

  it("rejects remote updater inventory with a package name or size mismatch", async () => {
    const verifier = await hostedReleaseVerifier();
    const version = "0.1.0-preview.1";
    const packageDigest = "b".repeat(64);
    const packageSha512 = Buffer.alloc(64, 4).toString("base64");
    const updater = [
      `version: ${version}`,
      "files:",
      "  - url: HyperGen-test.exe",
      `    sha512: ${packageSha512}`,
      "    size: 99",
      "path: HyperGen-test.exe",
      `sha512: ${packageSha512}`,
      "",
    ].join("\n");
    const dependencyHash = `${"a".repeat(64)}\n`;
    const updaterDigest = sha256(updater);
    const dependencyDigest = sha256(dependencyHash);
    const checksums = [
      `${packageDigest}  HyperGen-test.exe`,
      `${updaterDigest}  latest.yml`,
      `${dependencyDigest}  python-deps-hash.txt`,
      "",
    ].join("\n");
    const metadata = new Map<string, Buffer>([
      ["latest.yml", Buffer.from(updater)],
      ["python-deps-hash.txt", Buffer.from(dependencyHash)],
      ["windows-x64.SHA256SUMS", Buffer.from(checksums)],
    ]);
    const assets = [
      {
        id: 1,
        name: "HyperGen-test.exe",
        size: 100,
        state: "uploaded",
        digest: `sha256:${packageDigest}`,
      },
      ...[...metadata].map(([name, content], index) => ({
        id: index + 2,
        name,
        size: content.length,
        state: "uploaded",
        digest: `sha256:${sha256(content)}`,
      })),
    ];

    await assert.rejects(
      verifier.verifyHostedReleaseSnapshot({
        release: {
          draft: true,
          prerelease: true,
          target_commitish: "2".repeat(40),
          assets,
        },
        contract: {
          version,
          platforms: { windows: { packages: ["HyperGen-test.exe", "latest.yml"] } },
        },
        loadAsset: async (asset) => {
          const content = metadata.get(asset.name);
          assert.ok(content);
          return content;
        },
        expectedCommit: "2".repeat(40),
        resolvedCommit: "2".repeat(40),
      }),
      /updater|size|inventory/i,
    );
  });

  it("rejects a draft whose resolved tag commit differs from the workflow commit", async () => {
    const verifier = await hostedReleaseVerifier();
    const dependencyHash = Buffer.from(`${"a".repeat(64)}\n`);
    const dependencyDigest = sha256(dependencyHash);
    const checksums = Buffer.from(`${dependencyDigest}  python-deps-hash.txt\n`);
    const metadata = new Map<string, Buffer>([
      ["python-deps-hash.txt", dependencyHash],
      ["minimal.SHA256SUMS", checksums],
    ]);
    const assets = [...metadata].map(([name, content], index) => ({
      id: index + 1,
      name,
      size: content.length,
      state: "uploaded",
      digest: `sha256:${sha256(content)}`,
    }));
    await assert.rejects(
      verifier.verifyHostedReleaseSnapshot({
        release: {
          draft: true,
          prerelease: true,
          target_commitish: "main",
          assets,
        },
        contract: { version: "0.1.0-preview.1", platforms: {} },
        loadAsset: async (asset) => {
          const content = metadata.get(asset.name);
          assert.ok(content);
          return content;
        },
        expectedCommit: "2".repeat(40),
        resolvedCommit: "1".repeat(40),
      }),
      /commit|target/i,
    );
  });

  it("rejects hosted release assets at or above 2,000,000,000 bytes", async () => {
    const verifier = await hostedReleaseVerifier();
    await assert.rejects(
      verifier.verifyHostedReleaseSnapshot({
        release: {
          draft: true,
          prerelease: true,
          assets: [
            {
              id: 1,
              name: "HyperGen-too-large.exe",
              size: 2_000_000_000,
              state: "uploaded",
              digest: `sha256:${"0".repeat(64)}`,
            },
          ],
        },
        contract: { version: "0.1.0-preview.1", platforms: {} },
        loadAsset: async () => Buffer.alloc(0),
      }),
      /2,000,000,000-byte limit/,
    );
  });
});
