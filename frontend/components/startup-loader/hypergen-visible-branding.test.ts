import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("../../", import.meta.url));
const startupLoaderPath = fileURLToPath(new URL("./StartupLoader.tsx", import.meta.url));
const endpageLockupPath = fileURLToPath(new URL("./EndpageLockup.tsx", import.meta.url));
const pageLoaderPath = fileURLToPath(
  new URL("../../studio/components/PageLoader/PageLoader.tsx", import.meta.url),
);
const hypergenLogoPath = path.join(frontendRoot, "assets", "hypergen-logo.svg");

function source(pathname: string): string {
  return readFileSync(pathname, "utf8");
}

function assertImportsHyperGenLogo(moduleSource: string, modulePath: string): string {
  const logoImport = moduleSource.match(
    /import\s+([A-Za-z_$][\w$]*)\s+from\s+["']([^"']*hypergen-logo\.svg(?:\?react)?)["']/,
  );
  assert.ok(logoImport, `${modulePath} must import the shared HyperGen logo`);

  const [, binding, specifierWithQuery] = logoImport;
  const specifier = specifierWithQuery.replace(/\?react$/, "");
  const resolved = specifier.startsWith("@/")
    ? path.resolve(frontendRoot, specifier.slice(2))
    : path.resolve(path.dirname(modulePath), specifier);

  assert.equal(resolved, hypergenLogoPath);
  assert.match(moduleSource, new RegExp(`<${binding}\\b`));
  return binding;
}

describe("HyperGen loader branding", () => {
  it("uses HyperGen copy and an accessible product name on the startup loader", () => {
    const loader = source(startupLoaderPath);

    assert.match(loader, /aria-label=\{[^\n]*["']HyperGen["'][^\n]*\}/);
    assert.match(loader, /\bHyperGen\b/);
    assert.doesNotMatch(loader, /LTX Desktop|Lightricks/);
  });

  it("uses the shared HyperGen logo while preserving splash state and reduced motion", () => {
    const lockup = source(endpageLockupPath);
    const loader = source(startupLoaderPath);

    assertImportsHyperGenLogo(lockup, endpageLockupPath);
    assert.match(lockup, /(?:aria-label|alt|title)=["']HyperGen["']/);
    assert.match(lockup, /\bstill\?:\s*boolean\b/);
    assert.match(lockup, /\bpaused\?:\s*boolean\b/);
    assert.match(lockup, /\bstill\s*=\s*false\b/);
    assert.match(lockup, /\bpaused\s*=\s*false\b/);
    assert.ok(
      (lockup.match(/\bstill\b/g) ?? []).length > 1,
      "still must affect the rendered lockup",
    );
    assert.ok(
      (lockup.match(/\bpaused\b/g) ?? []).length > 1,
      "paused must affect the rendered lockup",
    );
    assert.doesNotMatch(lockup, /ltx-endpage\.json|LTX-Studio-logo\.svg/i);

    assert.match(loader, /usePrefersReducedMotion\(\)/);
    assert.match(loader, /if\s*\(reducedMotion\)\s*\{\s*setStarted\(true\)\s*return/);
    assert.match(loader, /if\s*\(reducedMotion\)\s*\{\s*finish\(\)/);
    assert.match(loader, /<EndpageLockup\s+paused=\{!started\}\s*\/>/);
  });

  it("uses the shared accessible HyperGen logo on PageLoader", () => {
    const loader = source(pageLoaderPath);

    assertImportsHyperGenLogo(loader, pageLoaderPath);
    assert.match(loader, /(?:aria-label|alt|title)=["']HyperGen["']/);
    assert.doesNotMatch(loader, /LTX-Studio-logo\.svg|\bLtxLogo\b/);
  });
});
