import { load } from "js-yaml";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

type PackageMetadata = {
  name?: string;
  author?: string | { name?: string; email?: string };
  homepage?: string;
  repository?: string | { url?: string };
  scripts?: Record<string, string>;
};

type ProtocolMetadata = {
  name?: string;
  schemes?: string[];
};

type PublishMetadata = {
  provider?: string;
  owner?: string;
  repo?: string;
  channel?: string;
};

type BuilderMetadata = {
  appId?: string;
  productName?: string;
  protocols?: ProtocolMetadata | ProtocolMetadata[];
  win?: { azureSignOptions?: unknown };
  nsis?: { shortcutName?: string };
  mac?: {
    notarize?: boolean;
    extendInfo?: { NSMicrophoneUsageDescription?: string };
  };
  linux?: { maintainer?: string };
  extraResources?: Array<{ from?: string; to?: string }>;
  publish?: PublishMetadata | PublishMetadata[];
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function readRepoFile(relativePath: string): string {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

describe("HyperGen package and installer identity", () => {
  test("publishes package metadata and unpacked launch commands under HyperGen", () => {
    const packageJson = JSON.parse(readRepoFile("package.json")) as PackageMetadata;
    const repository =
      typeof packageJson.repository === "string"
        ? packageJson.repository
        : packageJson.repository?.url;

    assert.equal(packageJson.name, "hypergen");
    assert.match(
      packageJson.homepage ?? "",
      /^https:\/\/github\.com\/vjk7989\/HyperGen\/?$/,
    );
    assert.match(
      repository ?? "",
      /^(?:git\+)?https:\/\/github\.com\/vjk7989\/HyperGen(?:\.git)?$/,
    );
    assert.match(packageJson.scripts?.["start:unpacked:mac"] ?? "", /HyperGen\.app/);
    assert.match(packageJson.scripts?.["start:unpacked:win"] ?? "", /HyperGen\.exe/);
  });

  test("keeps installer metadata HyperGen-owned, HyperGen-only, and unsigned", () => {
    const builderYaml = readRepoFile("electron-builder.yml");
    const builder = load(builderYaml) as BuilderMetadata;
    const protocols = Array.isArray(builder.protocols)
      ? builder.protocols
      : [builder.protocols];
    const hypergenProtocol = protocols.find((protocol) => protocol?.name === "HyperGen");
    const publishTargets = Array.isArray(builder.publish)
      ? builder.publish
      : [builder.publish];
    const githubPublish = publishTargets.find((target) => target?.provider === "github");

    assert.equal(builder.appId, "io.github.vjk7989.hypergen");
    assert.equal(builder.productName, "HyperGen");
    assert.ok(hypergenProtocol, "electron-builder must declare the HyperGen protocol");
    assert.deepEqual(hypergenProtocol.schemes, ["hypergen"]);
    assert.doesNotMatch(builderYaml, /ltxdesktop|ltx-desktop/i);
    assert.equal(builder.nsis?.shortcutName, "HyperGen");
    assert.match(builder.mac?.extendInfo?.NSMicrophoneUsageDescription ?? "", /HyperGen/);
    assert.doesNotMatch(
      builder.mac?.extendInfo?.NSMicrophoneUsageDescription ?? "",
      /LTX Desktop|Lightricks/i,
    );
    assert.equal(builder.win?.azureSignOptions, undefined);
    assert.notEqual(builder.mac?.notarize, true);
    assert.doesNotMatch(
      builderYaml,
      /publisherName|certificateProfileName|codeSigningAccountName/,
    );
    assert.deepEqual(githubPublish, {
      provider: "github",
      owner: "vjk7989",
      repo: "HyperGen",
      channel: "latest",
    });
  });

  test("provides a public HyperGen Contributors maintainer identity for Linux DEB", () => {
    const packageJson = JSON.parse(readRepoFile("package.json")) as PackageMetadata;
    const builder = load(readRepoFile("electron-builder.yml")) as BuilderMetadata;
    const authorName =
      typeof packageJson.author === "string"
        ? packageJson.author
        : packageJson.author?.name;
    const maintainer =
      (typeof packageJson.author === "object" ? packageJson.author.email : undefined) ??
      builder.linux?.maintainer ??
      "";
    const emailMatch = maintainer.match(/(?:^|<)([^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>?$/);

    assert.equal(authorName, "HyperGen Contributors");
    assert.ok(emailMatch, "Linux DEB metadata must include a valid maintainer email");
    assert.doesNotMatch(emailMatch[1], /@(?:localhost|example\.(?:com|org|net))$/i);
  });

  test("ships every cross-platform runtime window icon beside the packaged executable", () => {
    const builder = load(readRepoFile("electron-builder.yml")) as BuilderMetadata;
    const windowSource = readRepoFile("electron/window.ts");
    const resources = builder.extraResources ?? [];

    assert.match(
      windowSource,
      /process\.platform === ['"]win32['"] \? ['"]icon\.ico['"] : ['"]icon\.png['"]/,
    );
    for (const icon of ["icon.ico", "icon.png"]) {
      assert.ok(
        resources.some(
          (resource) => resource.from === `resources/${icon}` && resource.to === icon,
        ),
        `${icon} must be copied to the packaged resources directory used by createWindow`,
      );
    }
  });

  test("launches HyperGen artifact names from the core installer scripts", () => {
    const windowsInstaller = readRepoFile("scripts/create-installer.ps1");
    const unixInstaller = readRepoFile("scripts/create-installer.sh");

    assert.match(windowsInstaller, /HyperGen\.exe/);
    assert.doesNotMatch(windowsInstaller, /LTX Desktop\.exe/);
    assert.match(unixInstaller, /HyperGen\.app/);
    assert.match(unixInstaller, /HyperGen\.exe/);
    assert.match(unixInstaller, /\/hypergen\b/);
    assert.doesNotMatch(unixInstaller, /LTX Desktop\.(?:app|exe)|\/ltx-desktop\b/);
  });
});
