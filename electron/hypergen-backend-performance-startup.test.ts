import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = new URL("../", import.meta.url);

function source(relativePath: string): string {
  return readFileSync(new URL(relativePath, repoRoot), "utf8");
}

describe("HyperGen backend, performance runner, and startup identity", () => {
  it("publishes the backend package as hypergen-backend", () => {
    const pyproject = source("backend/pyproject.toml");
    const projectHeader = pyproject.match(/\[project\]([\s\S]*?)(?=\n\[|$)/)?.[1];

    assert.ok(projectHeader, "missing Python project metadata");
    assert.match(projectHeader, /^name\s*=\s*["']hypergen-backend["']\s*$/m);
    assert.match(projectHeader, /^description\s*=\s*["'][^"']+["']\s*$/m);
  });

  it("brands the performance runner while retaining its compatibility environment", () => {
    const readme = source("backend/performance_runner/README.md");
    const dashboard = source("backend/performance_runner/dashboard/index.html");
    const server = source("backend/performance_runner/dashboard/server.py");
    const config = source("backend/performance_runner/perf_config.py");
    const violations: string[] = [];

    for (const [surface, content] of Object.entries({ readme, dashboard, server })) {
      if (!/HyperGen/.test(content)) violations.push(`${surface} must name HyperGen`);
      if (/LTX Desktop|Lightricks/.test(content)) {
        violations.push(`${surface} still exposes legacy product branding`);
      }
    }

    if (!/return\s+Path\(base\)\s*\/\s*["']HyperGen["']/.test(config)) {
      violations.push("the default performance app-data folder must be HyperGen");
    }
    if (!/os\.environ\.get\(["']LTX_APP_DATA_DIR["']\)/.test(config)) {
      violations.push("LTX_APP_DATA_DIR compatibility must remain supported");
    }

    assert.deepEqual(violations, []);
  });

  it("does not import or ship the old endpage assets while preserving splash compatibility", () => {
    const loader = source("frontend/components/startup-loader/StartupLoader.tsx");
    const lockup = source("frontend/components/startup-loader/EndpageLockup.tsx");
    const assetDirectory = new URL("frontend/components/startup-loader/", repoRoot);
    const violations: string[] = [];

    for (const asset of ["ltx-endpage.json", "ltx-endpage.m4a"]) {
      if (loader.includes(asset) || lockup.includes(asset)) {
        violations.push(`startup still imports ${asset}`);
      }
      if (existsSync(fileURLToPath(new URL(asset, assetDirectory)))) {
        violations.push(`startup still ships ${asset}`);
      }
    }

    assert.match(loader, /sound\?:\s*boolean\s*\|\s*null/);
    assert.match(loader, /\bsound\s*=\s*true\b/);
    assert.match(loader, /usePrefersReducedMotion\(\)/);
    assert.match(loader, /if\s*\(reducedMotion\)\s*\{\s*setStarted\(true\)\s*return/);
    assert.match(loader, /if\s*\(reducedMotion\)\s*\{\s*finish\(\)/);
    assert.deepEqual(violations, []);
  });
});
