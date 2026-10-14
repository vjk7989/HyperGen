import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { components } from "../generated/backend-openapi.ts";

import {
  buildVideoProviderCandidate,
  createVideoProviderEditorState,
  getVideoProviderEditorViewModel,
  saveAndActivateVideoProvider,
  selectVideoProvider,
  updateVideoProviderDraft,
} from "./video-provider-editor.ts";

type VideoProviderSnapshot = components["schemas"]["VideoProviderSnapshot"];

const snapshot: VideoProviderSnapshot = {
  activeProvider: "local",
  providers: [
    {
      providerId: "local",
      displayName: "Local models",
      defaultBaseUrl: null,
      signupUrl: null,
      documentationUrl: "https://example.test/local",
      suggestedModelIds: ["ltx-2"],
      capabilities: { textToVideo: true },
    },
    {
      providerId: "fal",
      displayName: "fal.ai",
      defaultBaseUrl: "https://queue.fal.run",
      signupUrl: "https://example.test/fal-key",
      documentationUrl: "https://example.test/fal-docs",
      suggestedModelIds: ["fal-ai/kling-video/v3/standard/text-to-video"],
      capabilities: { textToVideo: true },
    },
    {
      providerId: "custom",
      displayName: "Custom endpoint",
      defaultBaseUrl: null,
      signupUrl: null,
      documentationUrl: "https://example.test/custom",
      suggestedModelIds: [],
      capabilities: { textToVideo: true },
    },
  ],
  profiles: [
    {
      providerId: "custom",
      baseUrl: "http://localhost:9080",
      modelId: "private-video-v2",
      hasApiKey: true,
    },
  ],
};

describe("video provider editor state", () => {
  it("restores curated endpoint and model defaults when a curated provider is selected", () => {
    const customState = createVideoProviderEditorState(snapshot, "custom");

    const falState = selectVideoProvider(customState, "fal");

    assert.equal(falState.selectedProviderId, "fal");
    assert.equal(falState.baseUrl, "https://queue.fal.run");
    assert.equal(falState.modelId, "fal-ai/kling-video/v3/standard/text-to-video");
    assert.equal(falState.apiKey, "");
    assert.equal(falState.hasStoredApiKey, false);
  });

  it("keeps a custom endpoint and model editable while treating credentials as optional", () => {
    const initial = createVideoProviderEditorState(snapshot, "custom");
    const edited = updateVideoProviderDraft(initial, {
      baseUrl: "http://192.168.1.25:8080",
      modelId: "my-video-model",
      apiKey: "",
    });

    assert.equal(initial.baseUrl, "http://localhost:9080");
    assert.equal(initial.modelId, "private-video-v2");
    assert.equal(initial.apiKey, "");
    assert.equal(initial.hasStoredApiKey, true);
    assert.deepEqual(buildVideoProviderCandidate(edited), {
      baseUrl: "http://192.168.1.25:8080",
      modelId: "my-video-model",
    });
  });

  it("never infers or redelivers a secret from a redacted profile snapshot", () => {
    const state = createVideoProviderEditorState(snapshot, "custom");

    assert.equal(state.apiKey, "");
    assert.equal(state.hasStoredApiKey, true);
    assert.equal("apiKey" in buildVideoProviderCandidate(state), false);

    const rotated = updateVideoProviderDraft(state, { apiKey: "new-secret" });
    assert.deepEqual(buildVideoProviderCandidate(rotated), {
      baseUrl: "http://localhost:9080",
      modelId: "private-video-v2",
      apiKey: "new-secret",
    });
  });
});

describe("neutral video provider editor view model", () => {
  it("hides provider fields for local mode and allows selection without a key", () => {
    const state = createVideoProviderEditorState(snapshot, "local");

    assert.deepEqual(getVideoProviderEditorViewModel(state), {
      mode: "local",
      displayName: "Local models",
      showEndpoint: false,
      endpointEditable: false,
      showModel: false,
      modelEditable: false,
      showCredential: false,
      credentialRequired: false,
      credentialStatus: "not-applicable",
      signupUrl: null,
      documentationUrl: "https://example.test/local",
      canSubmit: true,
    });
  });

  it("shows curated cloud configuration and distinguishes missing from stored credentials", () => {
    const missing = getVideoProviderEditorViewModel(
      createVideoProviderEditorState(snapshot, "fal"),
    );
    const storedSnapshot: VideoProviderSnapshot = {
      ...snapshot,
      profiles: [
        ...snapshot.profiles,
        {
          providerId: "fal",
          baseUrl: "https://queue.fal.run",
          modelId: "fal-ai/kling-video/v3/standard/text-to-video",
          hasApiKey: true,
        },
      ],
    };
    const stored = getVideoProviderEditorViewModel(
      createVideoProviderEditorState(storedSnapshot, "fal"),
    );

    assert.deepEqual(missing, {
      mode: "curated",
      displayName: "fal.ai",
      showEndpoint: true,
      endpointEditable: false,
      showModel: true,
      modelEditable: true,
      showCredential: true,
      credentialRequired: true,
      credentialStatus: "missing",
      signupUrl: "https://example.test/fal-key",
      documentationUrl: "https://example.test/fal-docs",
      canSubmit: false,
    });
    assert.deepEqual(stored, {
      ...missing,
      credentialStatus: "stored",
      canSubmit: true,
    });
  });

  it("shows editable custom fields, an optional credential, and no signup link", () => {
    const state = createVideoProviderEditorState(snapshot, "custom");

    assert.deepEqual(getVideoProviderEditorViewModel(state), {
      mode: "custom",
      displayName: "Custom endpoint",
      showEndpoint: true,
      endpointEditable: true,
      showModel: true,
      modelEditable: true,
      showCredential: true,
      credentialRequired: false,
      credentialStatus: "stored",
      signupUrl: null,
      documentationUrl: "https://example.test/custom",
      canSubmit: true,
    });
  });

  it("does not expose or invent a credential value from a redacted profile", () => {
    const state = createVideoProviderEditorState(snapshot, "custom");
    const view = getVideoProviderEditorViewModel(state);

    assert.equal(state.hasStoredApiKey, true);
    assert.equal(state.apiKey, "");
    assert.equal("apiKey" in view, false);
    assert.equal("credentialValue" in view, false);
  });
});

describe("video provider save workflow", () => {
  it("validates the unsaved candidate before saving and selecting it", async () => {
    const state = updateVideoProviderDraft(
      createVideoProviderEditorState(snapshot, "custom"),
      { apiKey: "candidate-secret" },
    );
    const calls: Array<{ operation: string; providerId?: string; body?: unknown }> = [];

    await saveAndActivateVideoProvider(state, {
      async validateVideoProvider(providerId, body) {
        calls.push({ operation: "validate", providerId, body });
        return {
          ok: true as const,
          data: {
            providerId,
            valid: true,
            validationMode: "connectivity",
          },
        };
      },
      async updateVideoProvider(providerId, body) {
        calls.push({ operation: "save", providerId, body });
        return {
          ok: true as const,
          data: {
            providerId: "custom" as const,
            baseUrl: body.baseUrl,
            modelId: body.modelId,
            hasApiKey: true,
          },
        };
      },
      async setActiveVideoProvider(body) {
        calls.push({ operation: "activate", body });
        return {
          ok: true as const,
          data: { activeProvider: body.providerId },
        };
      },
    });

    const candidate = {
      baseUrl: "http://localhost:9080",
      modelId: "private-video-v2",
      apiKey: "candidate-secret",
    };
    assert.deepEqual(calls, [
      { operation: "validate", providerId: "custom", body: candidate },
      { operation: "save", providerId: "custom", body: candidate },
      {
        operation: "activate",
        body: { providerId: "custom" },
      },
    ]);
  });

  it("does not save or activate when candidate validation fails", async () => {
    const state = createVideoProviderEditorState(snapshot, "custom");
    const calls: string[] = [];

    await assert.rejects(
      saveAndActivateVideoProvider(state, {
        async validateVideoProvider() {
          calls.push("validate");
          return {
            ok: true as const,
            data: {
              providerId: "custom",
              valid: false,
              validationMode: "connectivity",
            },
          };
        },
        async updateVideoProvider() {
          calls.push("save");
          throw new Error("save must not run");
        },
        async setActiveVideoProvider() {
          calls.push("activate");
          throw new Error("activate must not run");
        },
      }),
      /validation/i,
    );

    assert.deepEqual(calls, ["validate"]);
  });
});
