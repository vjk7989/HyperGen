import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { LOCAL_GENERATION_UNSUPPORTED_URLS } from "./local-generation-unsupported.ts";

function source(relativePath: string): string {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

function productCopyViolations(moduleSource: string, surface: string): string[] {
  const violations: string[] = [];
  if (!/HyperGen/.test(moduleSource)) violations.push(`${surface} must name HyperGen`);
  if (/LTX Desktop|LTX Remote|Lightricks/.test(moduleSource)) {
    violations.push(`${surface} still exposes legacy product branding`);
  }
  return violations;
}

describe("HyperGen supporting surfaces", () => {
  it("brands desktop pairing and every browser remote-client message as HyperGen", () => {
    const surfaces = new Map([
      ["desktop remote pairing", source("../views/RemotePairing.tsx")],
      ["remote pairing status", source("../remote/PairingMessage.tsx")],
      ["remote error boundary", source("../remote/App.tsx")],
      ["remote browser title", source("../remote/index.html")],
      ["remote server metadata and fallback", source("../../backend/remote/app.py")],
    ]);

    const violations: string[] = [];
    for (const [surface, moduleSource] of surfaces) {
      violations.push(...productCopyViolations(moduleSource, surface));
    }
    assert.deepEqual(violations, []);
  });

  it("returns users to HyperGen from both Hugging Face callback outcomes", () => {
    const handler = source("../../backend/handlers/hf_auth_handler.py");
    const successHtml = handler.match(/_SUCCESS_HTML\s*=\s*\(([\s\S]*?)\n\)/)?.[1];
    const errorHtml = handler.match(/_ERROR_HTML_TEMPLATE\s*=\s*\(([\s\S]*?)\n\)/)?.[1];

    assert.ok(successHtml, "missing Hugging Face success HTML");
    assert.ok(errorHtml, "missing Hugging Face error HTML");
    assert.deepEqual(
      [
        ...productCopyViolations(successHtml, "Hugging Face success HTML"),
        ...productCopyViolations(errorHtml, "Hugging Face error HTML"),
      ],
      [],
    );
  });

  it("uses HyperGen in audio, keyboard, and local-generation guidance", () => {
    const audioGuidance = source("../studio/screens/Feature/fields/audioAssetInput.ts");
    const keyboardGuidance = source("./keyboard-shortcuts.ts");
    const localGuidance = source("./local-generation-unsupported.ts");
    const violations: string[] = [];

    if (
      !/Extracting audio from video is only available in HyperGen\./.test(audioGuidance)
    ) {
      violations.push("audio extraction guidance must name HyperGen");
    }
    if (/LTX Desktop|Lightricks/.test(audioGuidance)) {
      violations.push("audio extraction guidance still uses legacy branding");
    }

    if (!/name:\s*["']HyperGen Default["']/.test(keyboardGuidance)) {
      violations.push("default keyboard preset must be named HyperGen Default");
    }
    if (
      !/description:\s*["']Default keyboard layout for HyperGen["']/.test(
        keyboardGuidance,
      )
    ) {
      violations.push("default keyboard guidance must name HyperGen");
    }
    if (
      /name:\s*["']LTX Default["']|Default keyboard layout for LTX Desktop|Lightricks/.test(
        keyboardGuidance,
      )
    ) {
      violations.push("keyboard guidance still uses legacy branding");
    }

    if (!/HyperGen/.test(localGuidance)) {
      violations.push("local-generation guidance must name HyperGen");
    }
    if (
      /LTX Desktop|Lightricks|LTX Explore|https:\/\/(?:app\.)?ltx\.io/.test(localGuidance)
    ) {
      violations.push("local-generation guidance still uses upstream product branding");
    }

    for (const [name, value] of Object.entries(LOCAL_GENERATION_UNSUPPORTED_URLS)) {
      const url = new URL(value);
      if (url.protocol !== "https:") violations.push(`${name} must use HTTPS`);
      if (
        url.hostname !== "github.com" ||
        url.pathname.replace(/\/$/, "") !== "/vjk7989/HyperGen"
      ) {
        violations.push(`${name} must target the HyperGen repository`);
      }
    }

    assert.deepEqual(violations, []);
  });
});
