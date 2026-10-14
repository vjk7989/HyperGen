import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function source(relativePath: string): string {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

function productionSourceFiles(relativePath: string): string[] {
  const absolutePath = path.join(repoRoot, relativePath);
  if (statSync(absolutePath).isDirectory()) {
    return readdirSync(absolutePath).flatMap((entry) =>
      productionSourceFiles(path.join(relativePath, entry)),
    );
  }
  if (/\.test\.[cm]?[jt]sx?$/.test(relativePath)) return [];
  return /\.[cm]?[jt]sx?$/.test(relativePath) ? [relativePath] : [];
}

describe("desktop product telemetry removal", () => {
  it("ships no Lightricks product-ingest endpoint", () => {
    const ingestEndpoint = ["https://ltx-desktop", "lightricks.com/v2/ingest"].join(".");
    const offenders = ["electron", "frontend", "shared"]
      .flatMap(productionSourceFiles)
      .filter((relativePath) => source(relativePath).includes(ingestEndpoint));

    assert.deepEqual(offenders, []);
  });

  it("deletes obsolete Electron telemetry and frontend opt-out modules", () => {
    const obsoletePaths = [
      "electron/analytics.ts",
      "electron/analytics-payload.ts",
      "electron/analytics-payload.test.ts",
      "electron/analytics-sink.ts",
      "electron/analytics-sink.test.ts",
      "electron/launched-event.ts",
      "electron/launched-event.test.ts",
      "frontend/components/first-run/SetupAnalyticsOptOut.tsx",
      "frontend/components/first-run/analytics-opt-out-write.ts",
      "frontend/components/first-run/analytics-opt-out-write.test.ts",
    ];
    const remaining = obsoletePaths.filter((relativePath) =>
      existsSync(path.join(repoRoot, relativePath)),
    );

    assert.deepEqual(remaining, []);
  });

  it("detaches Electron startup and the Python backend from product telemetry", () => {
    const main = source("electron/main.ts");
    const pythonBackend = source("electron/python-backend.ts");

    assert.doesNotMatch(main, /sendAnalyticsEvent|shouldSendLaunched/);
    assert.doesNotMatch(
      pythonBackend,
      /sendAnalyticsEvent|startAnalyticsSink|analytics-sink|analyticsSink|LTX_ANALYTICS_SINK_(?:URL|TOKEN)/,
    );
  });

  it("removes telemetry controls from Electron APIs and product UI", () => {
    assert.doesNotMatch(
      source("electron/ipc/app-handlers.ts"),
      /getAnalyticsState|setAnalyticsEnabled|notifyInstallStarted/,
    );
    assert.doesNotMatch(
      source("shared/electron-api-schema.ts"),
      /getAnalyticsState|setAnalyticsEnabled|notifyInstallStarted/,
    );
    assert.doesNotMatch(
      source("frontend/components/FirstRunSetup.tsx"),
      /SetupAnalyticsOptOut|flushAnalyticsOptOut|notifyInstallStarted/,
    );
    assert.doesNotMatch(
      source("frontend/components/SettingsModal.tsx"),
      /Anonymous Analytics|getAnalyticsState|setAnalyticsEnabled/,
    );
  });

  it("does not persist a product analytics preference or installation identifier", () => {
    assert.doesNotMatch(
      source("electron/app-state.ts"),
      /analyticsEnabled|installationId/,
    );
  });
});
