import { load as loadYaml } from "js-yaml";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

type CloudflaredArtifact = {
  asset: string;
  sha256: string;
  executable: string;
  archive?: boolean;
};

type CloudflaredPreparation = {
  CLOUDFLARED_VERSION: string;
  CLOUDFLARED_ARTIFACTS: Readonly<Record<string, CloudflaredArtifact>>;
};

type WorkflowStep = { name?: string; run?: string };
type Workflow = {
  jobs?: Record<string, { steps?: WorkflowStep[] }>;
};

type BuilderConfig = {
  extraResources?: Array<{
    from?: string;
    to?: string;
    filter?: string[];
  }>;
};

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

async function readRepoFile(relativePath: string): Promise<string> {
  return readFile(path.join(root, relativePath), "utf8");
}

async function preparationModule(): Promise<CloudflaredPreparation> {
  const url = pathToFileURL(path.join(root, "scripts", "prepare-cloudflared.mjs")).href;
  return import(url) as Promise<CloudflaredPreparation>;
}

function findStep(steps: WorkflowStep[], name: RegExp): WorkflowStep {
  const step = steps.find((candidate) => name.test(candidate.name ?? ""));
  assert.ok(step, `missing workflow step matching ${name}`);
  return step;
}

describe("bundled cloudflared packaging contract", () => {
  test("pins checksummed artifacts for every supported release target", async () => {
    const preparation = await preparationModule();

    assert.match(preparation.CLOUDFLARED_VERSION, /^\d{4}\.\d{1,2}\.\d+$/);
    assert.deepEqual(Object.keys(preparation.CLOUDFLARED_ARTIFACTS).sort(), [
      "darwin-arm64",
      "linux-x64",
      "win32-x64",
    ]);

    assert.deepEqual(
      Object.fromEntries(
        Object.entries(preparation.CLOUDFLARED_ARTIFACTS).map(([target, value]) => [
          target,
          {
            asset: value.asset,
            executable: value.executable,
            archive: value.archive ?? false,
          },
        ]),
      ),
      {
        "win32-x64": {
          asset: "cloudflared-windows-amd64.exe",
          executable: "cloudflared.exe",
          archive: false,
        },
        "linux-x64": {
          asset: "cloudflared-linux-amd64",
          executable: "cloudflared",
          archive: false,
        },
        "darwin-arm64": {
          asset: "cloudflared-darwin-arm64.tgz",
          executable: "cloudflared",
          archive: true,
        },
      },
    );

    const checksums = Object.values(preparation.CLOUDFLARED_ARTIFACTS).map(
      (artifact) => artifact.sha256,
    );
    assert.equal(new Set(checksums).size, checksums.length);
    for (const checksum of checksums) {
      assert.match(checksum, /^[a-f0-9]{64}$/);
      assert.notEqual(checksum, "0".repeat(64));
    }
  });

  test("packages only the platform cloudflared executable as an extra resource", async () => {
    const builder = loadYaml(await readRepoFile("electron-builder.yml")) as BuilderConfig;
    const resource = builder.extraResources?.find(
      (entry) => entry.from === "resources/cloudflared",
    );

    assert.ok(resource, "electron-builder must package resources/cloudflared");
    assert.equal(resource.to, "cloudflared");
    assert.deepEqual(
      new Set(resource.filter),
      new Set(["cloudflared", "cloudflared.exe"]),
    );
  });

  test("passes the packaged executable path to the Python backend while honoring overrides", async () => {
    const source = await readRepoFile("electron/python-backend.ts");
    const assignment = source.match(
      /HYPERGEN_CLOUDFLARED_PATH:\s*([\s\S]*?),\s*\.\.\.\(!isDev/,
    )?.[1];

    assert.ok(
      assignment,
      "Python backend environment must define HYPERGEN_CLOUDFLARED_PATH",
    );
    assert.match(assignment, /process\.env\.HYPERGEN_CLOUDFLARED_PATH\s*\?\?/);
    assert.match(
      assignment,
      /isDev\s*\?\s*getCurrentDir\(\)\s*:\s*process\.resourcesPath/,
    );
    assert.match(assignment, /['"]cloudflared['"]/);
    assert.match(
      assignment,
      /process\.platform\s*===\s*['"]win32['"]\s*\?\s*['"]cloudflared\.exe['"]\s*:\s*['"]cloudflared['"]/,
    );
  });

  test("prepares and verifies cloudflared in every native release job", async () => {
    const workflow = loadYaml(
      await readRepoFile(".github/workflows/release.yml"),
    ) as Workflow;
    const cases = [
      ["build-windows", /Build Windows x64 package/i, /cloudflared\.exe/],
      ["build-linux", /Build Linux x64 packages/i, /cloudflared\/cloudflared/],
      ["build-macos", /Build unsigned macOS arm64 packages/i, /cloudflared\/cloudflared/],
    ] as const;

    for (const [jobName, buildName, packagedBinary] of cases) {
      const steps = workflow.jobs?.[jobName]?.steps ?? [];
      const build = findStep(steps, buildName);
      const verify = findStep(steps, /Verify .*package metadata|Verify .*branding/i);
      const buildCommand = build.run ?? "";
      const verificationCommand = verify.run ?? "";

      assert.match(buildCommand, /pnpm prepare:cloudflared/);
      assert.match(buildCommand, /electron-builder/);
      assert.ok(
        buildCommand.indexOf("pnpm prepare:cloudflared") <
          buildCommand.indexOf("electron-builder"),
        `${jobName} must prepare cloudflared before packaging`,
      );
      assert.match(verificationCommand, packagedBinary);
    }
  });

  test("prepares cloudflared before every local Electron build entry", async () => {
    const packageJson = JSON.parse(await readRepoFile("package.json")) as {
      scripts?: Record<string, string>;
    };

    for (const scriptName of ["build", "build:skip-python", "build:fast"]) {
      const command = packageJson.scripts?.[scriptName] ?? "";
      const prepareIndex = command.indexOf("prepare:cloudflared");
      const buildIndex = command.indexOf("scripts/local-build");
      assert.ok(prepareIndex >= 0, `${scriptName} must prepare cloudflared`);
      assert.ok(buildIndex >= 0, `${scriptName} must run the local Electron build`);
      assert.ok(
        prepareIndex < buildIndex,
        `${scriptName} must prepare cloudflared before Electron packaging`,
      );
    }
  });
});
