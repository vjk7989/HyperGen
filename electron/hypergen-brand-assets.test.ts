import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pngSignature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function readAsset(relativePath: string): Buffer {
  return readFileSync(path.join(repoRoot, relativePath));
}

function assertPngDimensions(
  relativePath: string,
  width: number,
  height: number,
): Buffer {
  const png = readAsset(relativePath);
  assert.deepEqual(
    png.subarray(0, pngSignature.length),
    pngSignature,
    `${relativePath} is not PNG`,
  );
  assert.equal(
    png.subarray(12, 16).toString("ascii"),
    "IHDR",
    `${relativePath} has no IHDR`,
  );
  assert.equal(png.readUInt32BE(16), width, `${relativePath} width`);
  assert.equal(png.readUInt32BE(20), height, `${relativePath} height`);
  return png;
}

test("keeps the complete HyperGen installer icon inventory valid", () => {
  const master = assertPngDimensions(
    "resources/branding/hypergen-logo-master.png",
    1254,
    1254,
  );
  assert.equal(
    [4, 6].includes(master[25]),
    true,
    "HyperGen master PNG must use an alpha-capable colour type",
  );

  assertPngDimensions("resources/icon.png", 1024, 1024);
  assertPngDimensions("frontend/assets/hypergen-splash.png", 512, 512);
  assertPngDimensions("public/favicon.png", 32, 32);

  for (const size of [16, 24, 32, 48, 64, 128, 256, 512, 1024]) {
    assertPngDimensions(`resources/icons/${size}x${size}.png`, size, size);
  }

  for (const relativePath of ["resources/icon.ico", "public/favicon.ico"]) {
    const ico = readAsset(relativePath);
    assert.deepEqual([...ico.subarray(0, 4)], [0, 0, 1, 0], `${relativePath} is not ICO`);
    assert.equal(ico.readUInt16LE(4), 7, `${relativePath} icon directory count`);
  }

  const icns = readAsset("resources/icon.icns");
  assert.equal(icns.subarray(0, 4).toString("ascii"), "icns");
  assert.equal(icns.readUInt32BE(4), icns.length, "ICNS declared length");

  for (const relativePath of [
    "resources/icon_source.svg",
    "frontend/assets/hypergen-logo.svg",
  ]) {
    const svg = readAsset(relativePath).toString("utf8");
    assert.match(
      svg,
      /fill=["']currentColor["']/,
      `${relativePath} must inherit currentColor`,
    );
    assert.doesNotMatch(
      svg,
      /LTX Desktop|Lightricks/i,
      `${relativePath} has legacy branding`,
    );
  }
});
