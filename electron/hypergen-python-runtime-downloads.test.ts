import { load as loadYaml } from "js-yaml";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function readRepoFile(relativePath: string): string {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

function pythonVersion(): string {
  return readRepoFile("backend/.python-version").trim();
}

function standaloneTag(script: string): string {
  const match = script.match(/PBS_TAG="\$\{PBS_TAG:-([0-9]{8})\}"/);
  assert.ok(match, "prepare-python.sh must declare an explicit YYYYMMDD PBS_TAG");
  return match[1];
}

function standaloneUrl(version: string, tag: string, target: string): string {
  return (
    `https://github.com/astral-sh/python-build-standalone/releases/download/${tag}/` +
    `cpython-${version}+${tag}-${target}-install_only_stripped.tar.gz`
  );
}

describe("HyperGen packaged Python runtime downloads", () => {
  test("pins backend Python to one exact x.y.z release", () => {
    assert.match(pythonVersion(), /^\d+\.\d+\.\d+$/);
  });

  test("pins an explicit python-build-standalone release tag", () => {
    const script = readRepoFile("scripts/prepare-python.sh");
    assert.match(standaloneTag(script), /^\d{8}$/);
    assert.match(
      script,
      /cpython-\$\{PYTHON_VERSION\}\+\$\{PBS_TAG\}-\$\{PBS_ARCH\}-\$\{PBS_OS\}-install_only_stripped\.tar\.gz/,
    );
  });

  test("constructs current macOS arm64 and Linux x64 standalone asset names", () => {
    const version = pythonVersion();
    const tag = standaloneTag(readRepoFile("scripts/prepare-python.sh"));
    const macUrl = standaloneUrl(version, tag, "aarch64-apple-darwin");
    const linuxUrl = standaloneUrl(version, tag, "x86_64-unknown-linux-gnu");

    assert.match(
      macUrl,
      /^https:\/\/github\.com\/astral-sh\/python-build-standalone\/releases\/download\/\d{8}\/cpython-\d+\.\d+\.\d+\+\d{8}-aarch64-apple-darwin-install_only_stripped\.tar\.gz$/,
    );
    assert.match(
      linuxUrl,
      /^https:\/\/github\.com\/astral-sh\/python-build-standalone\/releases\/download\/\d{8}\/cpython-\d+\.\d+\.\d+\+\d{8}-x86_64-unknown-linux-gnu-install_only_stripped\.tar\.gz$/,
    );
  });

  test("uses the same exact Python release for the Windows embed archive", () => {
    const version = pythonVersion();
    const script = readRepoFile("scripts/prepare-python.ps1");
    const windowsUrl =
      `https://www.python.org/ftp/python/${version}/` +
      `python-${version}-embed-amd64.zip`;

    assert.match(
      script,
      /https:\/\/www\.python\.org\/ftp\/python\/\$PythonVersion\/python-\$PythonVersion-embed-amd64\.zip/,
    );
    assert.match(
      windowsUrl,
      /^https:\/\/www\.python\.org\/ftp\/python\/\d+\.\d+\.\d+\/python-\d+\.\d+\.\d+-embed-amd64\.zip$/,
    );
  });

  test("provisions the exact repository Python pin in the Windows release job", () => {
    const workflow = loadYaml(readRepoFile(".github/workflows/release.yml")) as {
      jobs?: Record<
        string,
        {
          steps?: Array<{
            uses?: string;
            with?: Record<string, unknown>;
          }>;
        }
      >;
    };
    const setupPython = workflow.jobs?.["build-windows"]?.steps?.find((step) =>
      String(step.uses ?? "").startsWith("actions/setup-python@"),
    );

    assert.ok(setupPython, "Windows release job must provision Python");
    assert.equal(setupPython.with?.["python-version"], pythonVersion());
  });

  test("prefers an exact PATH Python for Windows development files before the uv fallback", () => {
    const script = readRepoFile("scripts/prepare-python.ps1");
    const pathLookup = script.search(/Get-Command\s+(?:python|python3)(?:\.exe)?/i);
    const exactVersionCheck = script.search(/sys\.(?:version_info|version)/i);
    const exactVersionComparison = script.search(/-eq\s+\$PythonVersion\b/i);
    const uvInstallFallback = script.search(/uv python install\s+"?\$PythonVersion"?/i);
    const selectedPrefix = script.search(/sys\.prefix/i);

    assert.ok(pathLookup >= 0, "prepare-python.ps1 must inspect PATH Python first");
    assert.ok(
      exactVersionCheck >= pathLookup && exactVersionCheck < uvInstallFallback,
      "PATH Python must be checked against the exact runtime pin before fallback",
    );
    assert.ok(
      exactVersionComparison >= exactVersionCheck &&
        exactVersionComparison < uvInstallFallback,
      "PATH Python version must equal the repository runtime pin",
    );
    assert.ok(
      uvInstallFallback > pathLookup,
      "uv managed installation must remain as the local fallback",
    );
    assert.ok(
      selectedPrefix > pathLookup,
      "development files must come from the selected interpreter prefix",
    );
  });
});
