import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canDismissProviderConfiguration,
  resolveApiGatewayPlan,
  resolveGenerationPreflight,
  shouldAutomaticallySubmitAfterProviderConfiguration,
  shouldCloseProviderConfiguration,
} from "./provider-configuration-gate.ts";

describe("generation-blocking provider configuration gateway", () => {
  it("uses the shared video provider editor and never includes the legacy LTX key section", () => {
    assert.deepEqual(
      resolveApiGatewayPlan({
        kind: "video-provider",
        blocking: true,
        requiredKeys: ["ltx"],
      }),
      {
        content: "video-provider-editor",
        legacyKeySections: [],
        blocking: true,
      },
    );
  });

  it("closes provider configuration only after validate, save, and activate succeed", () => {
    for (const status of [
      "idle",
      "validating",
      "saving",
      "activating",
      "error",
    ] as const) {
      assert.equal(shouldCloseProviderConfiguration(status), false);
    }
    assert.equal(shouldCloseProviderConfiguration("succeeded"), true);
  });

  it("preserves the dedicated fal image-key gateway behavior", () => {
    assert.deepEqual(
      resolveApiGatewayPlan({
        kind: "api-keys",
        blocking: true,
        requiredKeys: ["fal"],
      }),
      {
        content: "legacy-api-keys",
        legacyKeySections: ["fal"],
        blocking: true,
      },
    );
  });

  it("lets users dismiss provider setup and return to exploring", () => {
    assert.equal(
      canDismissProviderConfiguration({
        blocking: true,
        configurationSucceeded: false,
      }),
      true,
    );
    assert.equal(
      canDismissProviderConfiguration({
        blocking: true,
        configurationSucceeded: true,
      }),
      true,
    );
    assert.equal(
      canDismissProviderConfiguration({
        blocking: false,
        configurationSucceeded: false,
      }),
      true,
    );
  });

  it("does not automatically submit a billable generation after setup succeeds", () => {
    assert.equal(shouldAutomaticallySubmitAfterProviderConfiguration("succeeded"), false);
  });
});
describe("generation preflight", () => {
  it("allows viable local and configured cloud generation paths", () => {
    assert.deepEqual(
      resolveGenerationPreflight({
        providerStatus: "ready",
        localInstallationViable: true,
        activeProviderId: "local",
        activeProviderConfigured: false,
      }),
      { kind: "ready" },
    );
    assert.deepEqual(
      resolveGenerationPreflight({
        providerStatus: "ready",
        localInstallationViable: false,
        activeProviderId: "runway",
        activeProviderConfigured: true,
      }),
      { kind: "ready" },
    );
  });

  it("routes an unconfigured cloud provider to provider setup before submission", () => {
    assert.deepEqual(
      resolveGenerationPreflight({
        providerStatus: "ready",
        localInstallationViable: true,
        activeProviderId: "fal",
        activeProviderConfigured: false,
      }),
      { kind: "configure-provider", providerId: "fal" },
    );
  });

  it("routes unavailable local generation to a local or API setup choice", () => {
    assert.deepEqual(
      resolveGenerationPreflight({
        providerStatus: "ready",
        localInstallationViable: false,
        activeProviderId: "local",
        activeProviderConfigured: false,
      }),
      { kind: "configure-local" },
    );
  });

  it("returns a retryable status error instead of submitting with stale provider state", () => {
    assert.deepEqual(
      resolveGenerationPreflight({
        providerStatus: "error",
        localInstallationViable: true,
        activeProviderId: "local",
        activeProviderConfigured: false,
      }),
      { kind: "status-error" },
    );
  });
});
