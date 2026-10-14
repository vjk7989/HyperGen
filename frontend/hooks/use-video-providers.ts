import { useCallback, useEffect, useState } from "react";

import type { components } from "../generated/backend-openapi.ts";
import { ApiClient } from "../lib/api-client.ts";
import {
  type ProviderId,
  type VideoProviderEditorState,
  createVideoProviderEditorState,
  saveAndActivateVideoProvider,
  selectVideoProvider,
  updateVideoProviderDraft,
} from "../lib/video-provider-editor.ts";

type VideoProviderSnapshot = components["schemas"]["VideoProviderSnapshot"];

export function useVideoProviders(enabled = true) {
  const [snapshot, setSnapshot] = useState<VideoProviderSnapshot | null>(null);
  const [editorState, setEditorState] = useState<VideoProviderEditorState | null>(null);
  const [isLoading, setIsLoading] = useState(enabled);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (preferredProviderId?: ProviderId) => {
    setIsLoading(true);
    setError(null);
    const result = await ApiClient.getVideoProviders();
    if (!result.ok) {
      const message = result.error.message || "Could not load video providers.";
      setError(message);
      setIsLoading(false);
      throw new Error(message);
    }
    setSnapshot(result.data);
    setEditorState((current) => {
      const providerId =
        preferredProviderId ??
        current?.selectedProviderId ??
        (result.data.activeProvider as ProviderId);
      return createVideoProviderEditorState(result.data, providerId);
    });
    setIsLoading(false);
    return result.data;
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refresh().catch(() => undefined);
  }, [enabled, refresh]);

  const selectProvider = useCallback((providerId: ProviderId) => {
    setError(null);
    setEditorState((current) =>
      current ? selectVideoProvider(current, providerId) : current,
    );
  }, []);

  const updateDraft = useCallback(
    (
      patch: Partial<Pick<VideoProviderEditorState, "baseUrl" | "modelId" | "apiKey">>,
    ) => {
      setError(null);
      setEditorState((current) =>
        current ? updateVideoProviderDraft(current, patch) : current,
      );
    },
    [],
  );

  const save = useCallback(async () => {
    if (!editorState) return;
    setIsSaving(true);
    setError(null);
    try {
      await saveAndActivateVideoProvider(editorState, ApiClient);
      await refresh(editorState.selectedProviderId);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Could not save video provider.";
      setError(message);
      throw caught;
    } finally {
      setIsSaving(false);
    }
  }, [editorState, refresh]);

  return {
    snapshot,
    editorState,
    isLoading,
    isSaving,
    error,
    refresh,
    selectProvider,
    updateDraft,
    save,
  };
}
