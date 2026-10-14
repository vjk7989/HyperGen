import type { components } from "../generated/backend-openapi.ts";

import type { createApiClient } from "./api-client.ts";

type ProviderDescriptor = components["schemas"]["ProviderDescriptor"];
export type ProviderId = ProviderDescriptor["providerId"];
type ProviderProfileUpdate = components["schemas"]["ProviderProfileUpdate"];
type VideoProviderSnapshot = components["schemas"]["VideoProviderSnapshot"];

export interface VideoProviderEditorState {
  snapshot: VideoProviderSnapshot;
  selectedProviderId: ProviderId;
  baseUrl: string;
  modelId: string;
  apiKey: string;
  hasStoredApiKey: boolean;
}

export interface VideoProviderEditorViewModel {
  mode: "local" | "curated" | "custom";
  displayName: string;
  showEndpoint: boolean;
  endpointEditable: boolean;
  showModel: boolean;
  modelEditable: boolean;
  showCredential: boolean;
  credentialRequired: boolean;
  credentialStatus: "not-applicable" | "missing" | "stored" | "entered";
  signupUrl: string | null;
  documentationUrl: string;
  canSubmit: boolean;
}

type VideoProviderEditorPatch = Partial<
  Pick<VideoProviderEditorState, "baseUrl" | "modelId" | "apiKey">
>;

type VideoProviderClient = Pick<
  ReturnType<typeof createApiClient>,
  "validateVideoProvider" | "updateVideoProvider" | "setActiveVideoProvider"
>;

function getDescriptor(
  snapshot: VideoProviderSnapshot,
  providerId: ProviderId,
): ProviderDescriptor {
  const descriptor = snapshot.providers.find((item) => item.providerId === providerId);
  if (!descriptor) throw new Error(`Unknown video provider: ${providerId}`);
  return descriptor;
}

export function createVideoProviderEditorState(
  snapshot: VideoProviderSnapshot,
  providerId: ProviderId = snapshot.activeProvider as ProviderId,
): VideoProviderEditorState {
  const descriptor = getDescriptor(snapshot, providerId);
  const profile = snapshot.profiles.find((item) => item.providerId === providerId);
  return {
    snapshot,
    selectedProviderId: providerId,
    baseUrl: profile?.baseUrl ?? descriptor.defaultBaseUrl ?? "",
    modelId: profile?.modelId ?? descriptor.suggestedModelIds[0] ?? "",
    apiKey: "",
    hasStoredApiKey: profile?.hasApiKey ?? false,
  };
}

export function selectVideoProvider(
  state: VideoProviderEditorState,
  providerId: ProviderId,
): VideoProviderEditorState {
  return createVideoProviderEditorState(state.snapshot, providerId);
}

export function updateVideoProviderDraft(
  state: VideoProviderEditorState,
  patch: VideoProviderEditorPatch,
): VideoProviderEditorState {
  return { ...state, ...patch };
}

export function buildVideoProviderCandidate(
  state: VideoProviderEditorState,
): ProviderProfileUpdate {
  const candidate: ProviderProfileUpdate = {
    baseUrl: state.baseUrl.trim() || null,
    modelId: state.modelId.trim() || null,
  };
  const apiKey = state.apiKey.trim();
  if (apiKey) candidate.apiKey = apiKey;
  return candidate;
}

export function getVideoProviderEditorViewModel(
  state: VideoProviderEditorState,
): VideoProviderEditorViewModel {
  const descriptor = getDescriptor(state.snapshot, state.selectedProviderId);
  if (state.selectedProviderId === "local") {
    return {
      mode: "local",
      displayName: descriptor.displayName,
      showEndpoint: false,
      endpointEditable: false,
      showModel: false,
      modelEditable: false,
      showCredential: false,
      credentialRequired: false,
      credentialStatus: "not-applicable",
      signupUrl: descriptor.signupUrl,
      documentationUrl: descriptor.documentationUrl,
      canSubmit: true,
    };
  }

  const isCustom = state.selectedProviderId === "custom";
  const hasEnteredApiKey = state.apiKey.trim().length > 0;
  const credentialStatus = hasEnteredApiKey
    ? "entered"
    : state.hasStoredApiKey
      ? "stored"
      : "missing";
  return {
    mode: isCustom ? "custom" : "curated",
    displayName: descriptor.displayName,
    showEndpoint: true,
    endpointEditable: isCustom,
    showModel: true,
    modelEditable: true,
    showCredential: true,
    credentialRequired: !isCustom,
    credentialStatus,
    signupUrl: descriptor.signupUrl,
    documentationUrl: descriptor.documentationUrl,
    canSubmit:
      state.baseUrl.trim().length > 0 &&
      state.modelId.trim().length > 0 &&
      (isCustom || credentialStatus !== "missing"),
  };
}

function resultMessage(
  result: { error?: { message?: string } },
  fallback: string,
): string {
  return result.error?.message ?? fallback;
}

export async function saveAndActivateVideoProvider(
  state: VideoProviderEditorState,
  client: VideoProviderClient,
): Promise<void> {
  const providerId = state.selectedProviderId;
  const candidate = buildVideoProviderCandidate(state);
  const validation = await client.validateVideoProvider(providerId, candidate);
  if (!validation.ok) {
    throw new Error(resultMessage(validation, "Video provider validation failed"));
  }
  if (!validation.data.valid) throw new Error("Video provider validation failed");

  if (providerId !== "local") {
    const saved = await client.updateVideoProvider(providerId, candidate);
    if (!saved.ok) throw new Error(resultMessage(saved, "Could not save video provider"));
  }

  const activated = await client.setActiveVideoProvider({ providerId });
  if (!activated.ok) {
    throw new Error(resultMessage(activated, "Could not select video provider"));
  }
}
