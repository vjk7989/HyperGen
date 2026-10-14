import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fixtureRoot = path.join(
  repoRoot,
  "electron",
  "fixtures",
  "hypergen-branding-guard",
);

function runBrandingGuard(fixture: "allowed" | "rejected") {
  return spawnSync(
    process.execPath,
    [
      path.join(repoRoot, "scripts", "check-product-branding.mjs"),
      "--root",
      path.join(fixtureRoot, fixture),
    ],
    {
      cwd: repoRoot,
      encoding: "utf8",
    },
  );
}

describe("HyperGen product-branding guard", () => {
  it("allows technical LTX identity, model dependency URLs, and legal notices", () => {
    const result = runBrandingGuard("allowed");

    assert.equal(
      result.status,
      0,
      `allowed references must pass\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
  });

  it("rejects legacy product identifiers and product website links", () => {
    const result = runBrandingGuard("rejected");
    const output = `${result.stdout}\n${result.stderr}`;

    assert.equal(result.status, 1, output);
    assert.match(output, /legacy-protocol\.ts:1/i);
    assert.match(output, /product-site\.md:1/i);
    assert.match(output, /ltxdesktop/i);
    assert.match(output, /ltx\.io/i);
  });

  it("rejects product-owned legacy names and reports every offending file", () => {
    const result = runBrandingGuard("rejected");
    const output = `${result.stdout}\n${result.stderr}`;

    assert.equal(result.status, 1, output);
    assert.match(output, /product-copy\.ts:1/i);
    assert.match(output, /product-copy\.ts:2/i);
    assert.match(output, /setup-guide\.md:1/i);
    assert.match(output, /LTX Desktop/i);
    assert.match(output, /Lightricks/i);
  });
});
