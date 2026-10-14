import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function source(relativePath: string): string {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

describe("HyperGen Electron runtime identity", () => {
  it("downloads current and staged Python runtimes from HyperGen releases", () => {
    const pythonSetup = source("electron/python-setup.ts");

    assert.match(
      pythonSetup,
      /https:\/\/github\.com\/vjk7989\/HyperGen\/releases\/download\/v\$\{version\}/,
    );
    assert.match(
      pythonSetup,
      /https:\/\/github\.com\/vjk7989\/HyperGen\/releases\/download\/v\$\{newVersion\}/,
    );
    assert.match(pythonSetup, /process\.env\.HYPERGEN_PYTHON_URL/);
    assert.doesNotMatch(pythonSetup, /\bLTX_PYTHON_URL\b/);
    assert.doesNotMatch(pythonSetup, /github\.com\/Lightricks\/ltx-desktop/i);
    assert.doesNotMatch(pythonSetup, /ltx-desktop-artifacts/i);
  });

  it("uses HyperGen in Electron logs and temporary recording paths", () => {
    const main = source("electron/main.ts");
    const winDllSearch = source("electron/win-dll-search.ts");
    const fileHandlers = source("electron/ipc/file-handlers.ts");

    assert.ok((main.match(/\[HyperGen\]/g) ?? []).length >= 2);
    assert.doesNotMatch(main, /\[LTX Desktop\]/);
    assert.ok((winDllSearch.match(/\[HyperGen\]/g) ?? []).length >= 2);
    assert.doesNotMatch(winDllSearch, /\[LTX Desktop\]/);
    assert.match(fileHandlers, /['"]hypergen-recordings['"]/);
    assert.doesNotMatch(fileHandlers, /['"]ltx-desktop-recordings['"]/);
  });

  it("uses HyperGen in browser and Windows installer metadata", () => {
    assert.match(source("index.html"), /<title>\s*HyperGen\s*<\/title>/);
    assert.match(
      source("resources/installer.nsh"),
      /^; Custom NSIS include for HyperGen installer$/m,
    );
  });
});
