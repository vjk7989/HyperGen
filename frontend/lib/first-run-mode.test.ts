import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveFirstRunModePlan } from "./first-run-mode.ts";

const localReady = {
  huggingFaceAuthenticated: true,
  modelAccessGranted: true,
  localDownloadsRequired: true,
};

describe("resolveFirstRunModePlan", () => {
  it("completes explore mode without credentials, access, or local downloads", () => {
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "explore",
        activeProviderId: "local",
        activeProviderConfigured: false,
        local: {
          huggingFaceAuthenticated: false,
          modelAccessGranted: false,
          localDownloadsRequired: true,
        },
      }),
      {
        mode: "explore",
        action: "complete",
        blocker: null,
        shouldStartLocalDownloads: false,
      },
    );
  });

  it("completes API setup with a configured non-local provider without local downloads", () => {
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "api",
        activeProviderId: "fal",
        activeProviderConfigured: true,
        local: {
          huggingFaceAuthenticated: false,
          modelAccessGranted: false,
          localDownloadsRequired: true,
        },
      }),
      {
        mode: "api",
        action: "complete",
        blocker: null,
        shouldStartLocalDownloads: false,
      },
    );
  });

  it("blocks API setup until a non-local provider is configured", () => {
    for (const [activeProviderId, activeProviderConfigured] of [
      ["local", true],
      ["fal", false],
    ] as const) {
      assert.deepEqual(
        resolveFirstRunModePlan({
          mode: "api",
          activeProviderId,
          activeProviderConfigured,
          local: localReady,
        }),
        {
          mode: "api",
          action: "configure-provider",
          blocker: "provider-configuration",
          shouldStartLocalDownloads: false,
        },
      );
    }
  });

  it("preserves Hugging Face authentication and model-access gates in local mode", () => {
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "local",
        activeProviderId: "local",
        activeProviderConfigured: true,
        local: {
          ...localReady,
          huggingFaceAuthenticated: false,
        },
      }),
      {
        mode: "local",
        action: "authenticate-hugging-face",
        blocker: "hugging-face-authentication",
        shouldStartLocalDownloads: false,
      },
    );
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "local",
        activeProviderId: "local",
        activeProviderConfigured: true,
        local: {
          ...localReady,
          modelAccessGranted: false,
        },
      }),
      {
        mode: "local",
        action: "request-model-access",
        blocker: "model-access",
        shouldStartLocalDownloads: false,
      },
    );
  });

  it("keeps the existing local download path once access requirements pass", () => {
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "local",
        activeProviderId: "local",
        activeProviderConfigured: true,
        local: localReady,
      }),
      {
        mode: "local",
        action: "download-local-models",
        blocker: null,
        shouldStartLocalDownloads: true,
      },
    );
    assert.deepEqual(
      resolveFirstRunModePlan({
        mode: "local",
        activeProviderId: "local",
        activeProviderConfigured: true,
        local: {
          ...localReady,
          localDownloadsRequired: false,
        },
      }),
      {
        mode: "local",
        action: "complete",
        blocker: null,
        shouldStartLocalDownloads: false,
      },
    );
  });

  it("does not carry blockers across mode switches", () => {
    const apiBlocked = resolveFirstRunModePlan({
      mode: "api",
      activeProviderId: "local",
      activeProviderConfigured: false,
      local: localReady,
    });
    const localAfterApi = resolveFirstRunModePlan({
      mode: "local",
      activeProviderId: "local",
      activeProviderConfigured: false,
      local: localReady,
    });
    const localBlocked = resolveFirstRunModePlan({
      mode: "local",
      activeProviderId: "local",
      activeProviderConfigured: true,
      local: {
        ...localReady,
        huggingFaceAuthenticated: false,
      },
    });
    const apiAfterLocal = resolveFirstRunModePlan({
      mode: "api",
      activeProviderId: "fal",
      activeProviderConfigured: true,
      local: {
        ...localReady,
        huggingFaceAuthenticated: false,
      },
    });

    assert.equal(apiBlocked.blocker, "provider-configuration");
    assert.equal(localAfterApi.blocker, null);
    assert.equal(localAfterApi.action, "download-local-models");
    assert.equal(localBlocked.blocker, "hugging-face-authentication");
    assert.equal(apiAfterLocal.blocker, null);
    assert.equal(apiAfterLocal.action, "complete");
    assert.equal(apiAfterLocal.shouldStartLocalDownloads, false);
  });
});
