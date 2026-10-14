import assert from "node:assert/strict";
import { describe, it } from "node:test";
import path from "path";

import { registerDeepLinkProtocolClient } from "./deep-link-protocol.ts";

describe("registerDeepLinkProtocolClient", () => {
  it("registers the HyperGen scheme for the packaged app", () => {
    const calls: unknown[][] = [];
    registerDeepLinkProtocolClient(
      (...args) => {
        calls.push(args);
        return true;
      },
      {
        defaultApp: false,
        execPath: "/Applications/HyperGen.app/Contents/MacOS/HyperGen",
        argv: ["/Applications/HyperGen.app/Contents/MacOS/HyperGen"],
      },
    );
    assert.deepEqual(calls, [["hypergen"]]);
  });

  it("registers the HyperGen scheme against this repo during `pnpm dev`", () => {
    const calls: unknown[][] = [];
    registerDeepLinkProtocolClient(
      (...args) => {
        calls.push(args);
        return true;
      },
      {
        defaultApp: true,
        execPath: "/usr/local/bin/electron",
        argv: ["/usr/local/bin/electron", "."],
      },
    );
    assert.deepEqual(calls, [
      ["hypergen", "/usr/local/bin/electron", [path.resolve(".")]],
    ]);
  });
});
