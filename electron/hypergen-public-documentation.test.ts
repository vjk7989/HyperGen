import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = new URL("../", import.meta.url);

function source(relativePath: string): string {
  return readFileSync(new URL(relativePath, repoRoot), "utf8");
}

function section(markdown: string, heading: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex((line) => line.trim() === `## ${heading}`);
  if (start < 0) return "";

  const nextHeading = lines.findIndex(
    (line, index) => index > start && /^##\s+\S/.test(line),
  );
  return lines.slice(start + 1, nextHeading < 0 ? undefined : nextHeading).join("\n");
}

function missingContracts(
  documentName: string,
  content: string,
  contracts: Array<[label: string, pattern: RegExp]>,
): string[] {
  return contracts.flatMap(([label, pattern]) =>
    pattern.test(content) ? [] : [`${documentName} must document ${label}`],
  );
}

describe("HyperGen public documentation identity", () => {
  it("presents HyperGen as its own product in the README", () => {
    const readme = source("README.md");
    const imageTags = readme.match(/<img\b[^>]*>|!\[[^\]]*\]\([^)]+\)/gi) ?? [];
    const violations: string[] = [];

    if (!/^# HyperGen\s*$/m.test(readme))
      violations.push("README heading must be HyperGen");
    if (!/\bHyperGen is\b/.test(readme))
      violations.push("README introduction must name HyperGen");
    if (
      !imageTags.some(
        (tag) => /HyperGen/i.test(tag) && /hypergen-logo|resources\/icon\.png/i.test(tag),
      )
    ) {
      violations.push("README must show a HyperGen logo with HyperGen alternative text");
    }
    if (!/https:\/\/github\.com\/vjk7989\/HyperGen(?:\b|\/)/.test(readme)) {
      violations.push("README must link to the HyperGen repository");
    }
    if (/LTX[ -]?Desktop|Lightricks|ltxdesktop|ltx-desktop/i.test(readme)) {
      violations.push("README must not use legacy product names or identifiers");
    }
    if (/https?:\/\/(?:www\.)?ltx\.(?:io|video)/i.test(readme)) {
      violations.push("README must not link to legacy product websites");
    }
    assert.equal(existsSync(fileURLToPath(new URL("LICENSE.txt", repoRoot))), true);
    assert.equal(existsSync(fileURLToPath(new URL("NOTICES.md", repoRoot))), true);
    assert.deepEqual(violations, []);
  });

  it("uses HyperGen product language in public guides and development scripts", () => {
    const publicGuides = [
      "docs/INSTALLER.md",
      "docs/CONTRIBUTING.md",
      "docs/remote-lan.md",
    ];
    const brandedScripts = [
      "scripts/setup-dev.ps1",
      "scripts/setup-dev.sh",
      "scripts/local-build.ps1",
      "scripts/local-build.sh",
    ];
    const violations: string[] = [];

    for (const path of [...publicGuides, ...brandedScripts]) {
      const content = source(path);
      if (!/HyperGen/.test(content)) violations.push(`${path} must name HyperGen`);
      if (/LTX Desktop|Lightricks/.test(content)) {
        violations.push(`${path} still uses legacy product branding`);
      }
    }

    const performanceLauncher = source("scripts/perf-dev.mjs");
    if (!/APP_FOLDER_NAME\s*=\s*["']HyperGen["']/.test(performanceLauncher)) {
      violations.push("scripts/perf-dev.mjs must use the HyperGen app-data folder");
    }
    if (!/\bLTX_APP_DATA_DIR\b/.test(performanceLauncher)) {
      violations.push("scripts/perf-dev.mjs must retain LTX_APP_DATA_DIR compatibility");
    }

    assert.deepEqual(violations, []);
  });

  it("states that HyperGen sends no product telemetry", () => {
    const readmeTelemetry = section(source("README.md"), "Telemetry");
    const telemetryGuide = source("docs/TELEMETRY.md");
    const violations: string[] = [];
    const noTelemetryStatement =
      /HyperGen\s+(?:does not|doesn't)\s+(?:send|collect)\s+(?:product\s+)?(?:telemetry|analytics)|HyperGen\s+sends\s+no\s+(?:product\s+)?(?:telemetry|analytics)/i;

    if (!readmeTelemetry) violations.push("README must retain a Telemetry section");
    if (!noTelemetryStatement.test(readmeTelemetry)) {
      violations.push("README must state that HyperGen sends no product telemetry");
    }
    if (
      /Anonymous Analytics|analyticsEnabled|enabled by default|collects minimal/i.test(
        readmeTelemetry,
      )
    ) {
      violations.push(
        "README still documents removed product telemetry controls or collection",
      );
    }
    if (!noTelemetryStatement.test(telemetryGuide)) {
      violations.push(
        "docs/TELEMETRY.md must state that HyperGen sends no product telemetry",
      );
    }
    if (
      /Anonymous Analytics|analyticsEnabled|Opt out of basic analytics|installation ID|analytics-sink|analytics-payload/i.test(
        telemetryGuide,
      )
    ) {
      violations.push(
        "docs/TELEMETRY.md still documents removed telemetry delivery or controls",
      );
    }

    assert.deepEqual(violations, []);
  });

  it("links the provider, privacy, custom endpoint, and installer guides from the README", () => {
    const readme = source("README.md");
    const requiredLinks = [
      "docs/PROVIDERS.md",
      "docs/custom-provider.md",
      "docs/PRIVACY.md",
      "docs/INSTALLER.md",
    ];

    for (const target of requiredLinks) {
      assert.match(
        readme,
        new RegExp(`\\[[^\\]]+\\]\\(${target.replace(".", "\\.")}\\)`, "i"),
        `README must link to ${target}`,
      );
    }
  });

  it("documents the approved provider, privacy, release, and attribution contracts", () => {
    const providers = source("docs/PROVIDERS.md");
    const customProvider = source("docs/custom-provider.md");
    const privacy = source("docs/PRIVACY.md");
    const installer = source("docs/INSTALLER.md");
    const notices = source("NOTICES.md");
    const violations = [
      ...missingContracts("docs/PROVIDERS.md", providers, [
        [
          "the text-to-video-only provider scope",
          /Only \*\*text-to-video\*\* uses the general provider boundary/i,
        ],
        [
          "all curated providers and the custom endpoint",
          /LTX API[\s\S]*fal\.ai[\s\S]*Replicate[\s\S]*Runway[\s\S]*Luma[\s\S]*Google Veo[\s\S]*Custom endpoint/i,
        ],
        ["editable model identifiers", /model ID remains editable/i],
        ["plaintext credential storage", /stored locally in plaintext/i],
        ["redacted credential responses", /`hasApiKey`[\s\S]*redact/i],
      ]),
      ...missingContracts("docs/custom-provider.md", customProvider, [
        ["the asynchronous submit endpoint", /POST \/v1\/text-to-video\b/],
        ["the asynchronous status endpoint", /GET \/v1\/text-to-video\/\{id\}/],
        ["the cancellation endpoint", /POST \/v1\/text-to-video\/\{id\}\/cancel/],
        ["optional bearer authentication", /Authentication is optional/i],
        [
          "HTTPS for public endpoints",
          /Public base URLs and public result URLs must use HTTPS/i,
        ],
        [
          "HTTP support for private self-hosting",
          /HTTP base URLs are permitted for `localhost`[\s\S]*private-network/i,
        ],
      ]),
      ...missingContracts("docs/PRIVACY.md", privacy, [
        [
          "plaintext local credential storage",
          /stored in plaintext[\s\S]*video-providers\.json/i,
        ],
        ["redacted provider credentials", /`hasApiKey`[\s\S]*redacts credentials/i],
        [
          "provider request data flow",
          /API text-to-video sends the prompt[\s\S]*selected provider/i,
        ],
        ["the no-product-telemetry policy", /HyperGen sends no product telemetry/i],
      ]),
      ...missingContracts("docs/INSTALLER.md", installer, [
        [
          "GitHub Actions as the official build service",
          /built only by GitHub Actions on native runners/i,
        ],
        ["Windows x64 packages", /Windows x64:[^\n]*NSIS/i],
        ["Linux x64 packages", /Linux x64:[^\n]*AppImage and DEB/i],
        ["macOS arm64 packages", /macOS arm64:[^\n]*DMG and ZIP/i],
        ["the unsigned preview policy", /preview releases are \*\*unsigned\*\*/i],
      ]),
      ...missingContracts("NOTICES.md", notices, [
        [
          "linked LTX Desktop upstream attribution",
          /derived from \[LTX Desktop\]\(https:\/\/github\.com\/Lightricks\/LTX-Desktop\)/i,
        ],
        ["Lightricks authorship", /originally developed by Lightricks Ltd\./i],
      ]),
    ];

    assert.deepEqual(violations, []);
  });

  it("uses HyperGen privacy copy in first run while retaining the LTX model license", () => {
    const legalLinks = source("frontend/lib/legal-links.ts");
    const disclaimer = source("frontend/components/first-run/SetupLegalDisclaimer.tsx");
    const violations = [
      ...missingContracts("frontend/lib/legal-links.ts", legalLinks, [
        [
          "the HyperGen privacy URL",
          /HYPERGEN_PRIVACY_URL\s*=\s*[\r\n\s]*["']https:\/\/github\.com\/vjk7989\/HyperGen\/blob\/main\/docs\/PRIVACY\.md["']/,
        ],
        [
          "the LTX Community License URL",
          /LTX_COMMUNITY_LICENSE_URL\s*=\s*[\r\n\s]*["']https:\/\/github\.com\/Lightricks\/LTX-2\/blob\/main\/LICENSE["']/,
        ],
      ]),
      ...missingContracts("SetupLegalDisclaimer.tsx", disclaimer, [
        [
          "the HyperGen privacy link and label",
          /<LegalLink href=\{HYPERGEN_PRIVACY_URL\}>HyperGen privacy statement<\/LegalLink>/,
        ],
        [
          "the LTX Community License link and label",
          /<LegalLink href=\{LTX_COMMUNITY_LICENSE_URL\}>LTX Community License<\/LegalLink>/,
        ],
      ]),
    ];

    assert.doesNotMatch(disclaimer, /LTX privacy|Lightricks privacy/i);
    assert.deepEqual(violations, []);
  });
});
