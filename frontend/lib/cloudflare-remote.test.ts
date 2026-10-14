import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  type RemoteExposure,
  isRemoteExposureEnabled,
  nextRemoteExposure,
} from "./remote-exposure.ts";
import { pairingUrlFromStatus } from "./remote-pairing-screen.ts";

describe("Cloudflare remote exposure", () => {
  it("keeps disabled and local modes unchanged", () => {
    assert.equal(isRemoteExposureEnabled("off"), false);
    assert.equal(isRemoteExposureEnabled("lan"), true);
    assert.equal(nextRemoteExposure("off"), "lan");
    assert.equal(nextRemoteExposure("lan"), "off");
  });

  it("recognizes Cloudflare as an enabled exposure mode", () => {
    const exposure: RemoteExposure = "cloudflare";
    assert.equal(isRemoteExposureEnabled(exposure), true);
  });
});

describe("pairingUrlFromStatus", () => {
  const base = {
    permitted: true,
    serving: true,
    reason: null,
    mode: "cloudflare" as const,
    tunnelState: "ready" as const,
  };

  it("uses the public pairing URL for copy and QR when the tunnel is ready", () => {
    assert.equal(
      pairingUrlFromStatus({
        ...base,
        publicUrl: "https://quiet-sun.trycloudflare.com/pairing?t=one-time-grant",
        lanUrl: "http://192.168.0.12:41955/pairing?t=one-time-grant",
        url: "https://quiet-sun.trycloudflare.com/pairing?t=one-time-grant",
      }),
      "https://quiet-sun.trycloudflare.com/pairing?t=one-time-grant",
    );
  });

  it("keeps using the LAN pairing URL in local mode", () => {
    assert.equal(
      pairingUrlFromStatus({
        ...base,
        mode: "lan",
        tunnelState: "off",
        publicUrl: null,
        lanUrl: "http://192.168.0.12:41955/pairing?t=local-grant",
        url: "http://192.168.0.12:41955/pairing?t=local-grant",
      }),
      "http://192.168.0.12:41955/pairing?t=local-grant",
    );
  });

  it("does not expose a malformed public URL and falls back to a valid LAN URL", () => {
    assert.equal(
      pairingUrlFromStatus({
        ...base,
        publicUrl: "https://trycloudflare.com.evil.example/pairing?t=stolen",
        lanUrl: "http://192.168.0.12:41955/pairing?t=safe",
        url: "https://trycloudflare.com.evil.example/pairing?t=stolen",
      }),
      "http://192.168.0.12:41955/pairing?t=safe",
    );
  });

  it("requires a one-time pairing grant in public and local URLs", () => {
    assert.equal(
      pairingUrlFromStatus({
        ...base,
        publicUrl: "https://quiet-sun.trycloudflare.com/pairing",
        lanUrl: null,
        url: null,
      }),
      null,
    );
  });
});
