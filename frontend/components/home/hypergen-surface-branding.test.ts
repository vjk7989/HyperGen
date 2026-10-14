import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { HOME_EXTERNAL_URLS } from "./home-external-links.ts";

const frontendRoot = fileURLToPath(new URL("../../", import.meta.url));
const homeLogoPath = fileURLToPath(new URL("./HomeLogoButton.tsx", import.meta.url));
const aboutSettingsPath = fileURLToPath(
  new URL("../settings/AboutSettingsSection.tsx", import.meta.url),
);
const editorMenusPath = fileURLToPath(
  new URL("../../views/editor/buildMenuDefinitions.ts", import.meta.url),
);
const hypergenLogoPath = path.join(frontendRoot, "assets", "hypergen-logo.svg");

function source(pathname: string): string {
  return readFileSync(pathname, "utf8");
}

function assertSharedLogoImport(moduleSource: string): string {
  const logoImport = moduleSource.match(
    /import\s+([A-Za-z_$][\w$]*)\s+from\s+["']([^"']*hypergen-logo\.svg(?:\?react)?)["']/,
  );
  assert.ok(logoImport, "HomeLogoButton must import the shared HyperGen logo");

  const [, binding, specifierWithQuery] = logoImport;
  const specifier = specifierWithQuery.replace(/\?react$/, "");
  const resolved = specifier.startsWith("@/")
    ? path.resolve(frontendRoot, specifier.slice(2))
    : path.resolve(path.dirname(homeLogoPath), specifier);

  assert.equal(resolved, hypergenLogoPath);
  return binding;
}

describe("HyperGen product surfaces", () => {
  it("uses the shared logo with an accessible HyperGen title on Home", () => {
    const homeLogo = source(homeLogoPath);
    const logoBinding = assertSharedLogoImport(homeLogo);

    assert.match(
      homeLogo,
      new RegExp(`<${logoBinding}\\b[^>]*\\btitle=["']HyperGen["']`),
    );
    assert.doesNotMatch(homeLogo, /LTX-logo\.svg|\bLtxLogo\b|title=["']LTX["']/);
  });

  it("shows HyperGen's Apache license while retaining the LTX-2 model license", () => {
    const about = source(aboutSettingsPath);

    assert.match(about, />\s*HyperGen\s*</);
    assert.match(about, /HyperGen is licensed under the Apache License, Version 2\.0\./);
    assert.match(about, /title=["']LTX-2 model license["']/);
    assert.match(about, /The LTX-2 model uses the LTX-2 Community License Agreement/);
    assert.doesNotMatch(about, /LTX Desktop|Copyright © 2026 Lightricks/);
  });

  it("names HyperGen in editor Help and uses HyperGen support destinations", () => {
    const editorMenus = source(editorMenusPath);
    const violations: string[] = [];

    assert.match(editorMenus, /id:\s*["']help["'],\s*label:\s*["']Help["']/);
    if (!/id:\s*["']about["'],\s*label:\s*["']About HyperGen["']/.test(editorMenus)) {
      violations.push("editor Help must label its About item 'About HyperGen'");
    }
    if (/About LTX Desktop/.test(editorMenus)) {
      violations.push("editor Help still contains the legacy product name");
    }

    for (const [name, value] of Object.entries({
      support: HOME_EXTERNAL_URLS.support,
      reportIssue: HOME_EXTERNAL_URLS.reportIssue,
    })) {
      const url = new URL(value);
      if (url.protocol !== "https:") violations.push(`${name} must use HTTPS`);
      if (
        url.hostname !== "github.com" ||
        !/^\/vjk7989\/HyperGen(?:\/|$)/.test(url.pathname)
      ) {
        violations.push(`${name} must target the HyperGen GitHub repository`);
      }
    }
    if (
      new URL(HOME_EXTERNAL_URLS.reportIssue).pathname !== "/vjk7989/HyperGen/issues/new"
    ) {
      violations.push("reportIssue must open HyperGen's new-issue form");
    }

    assert.deepEqual(violations, []);
  });
});
