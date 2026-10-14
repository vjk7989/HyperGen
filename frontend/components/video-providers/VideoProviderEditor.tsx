import { Button } from "@ds/Button/Button";
import { Text } from "@ds/Text/Text";
import { TextField } from "@ds/TextField/TextField";
import { useEffect, useMemo } from "react";

import { useVideoProviders } from "@/hooks/use-video-providers";
import {
  type ProviderId,
  getVideoProviderEditorViewModel,
} from "@/lib/video-provider-editor";

import styles from "./VideoProviderEditor.module.scss";

const PROVIDER_DESCRIPTIONS: Record<ProviderId, string> = {
  local: "Generate on this device with installed models.",
  ltx: "Use hosted LTX text-to-video models.",
  fal: "Run text-to-video models through fal.ai.",
  replicate: "Use text-to-video models hosted on Replicate.",
  runway: "Create videos with the Runway API.",
  luma: "Create videos with Luma Dream Machine.",
  google_veo: "Generate with Veo through the Gemini API.",
  custom: "Connect a compatible self-hosted endpoint.",
};

function getProviderStatus(
  providerId: ProviderId,
  snapshot: NonNullable<ReturnType<typeof useVideoProviders>["snapshot"]>,
): { label: string; tone: "neutral" | "success" | "warning" } {
  if (providerId === "local") return { label: "On device", tone: "neutral" };

  const profile = snapshot.profiles.find((item) => item.providerId === providerId);
  if (providerId === "custom") {
    if (profile?.baseUrl && profile.modelId) {
      return { label: "Configured", tone: "success" };
    }
    return { label: "Optional key", tone: "neutral" };
  }
  if (profile?.hasApiKey) return { label: "Configured", tone: "success" };
  return { label: "API key required", tone: "warning" };
}

export function VideoProviderEditor({
  includeLocal = true,
  onSaved,
  className,
}: {
  includeLocal?: boolean;
  onSaved?: (providerId: ProviderId) => void | Promise<void>;
  className?: string;
}) {
  const providers = useVideoProviders();
  const availableDescriptors = useMemo(
    () =>
      providers.snapshot?.providers.filter(
        (descriptor) => includeLocal || descriptor.providerId !== "local",
      ) ?? [],
    [includeLocal, providers.snapshot],
  );

  useEffect(() => {
    if (
      includeLocal ||
      !providers.editorState ||
      providers.editorState.selectedProviderId !== "local"
    ) {
      return;
    }
    const firstCloudProvider = availableDescriptors[0];
    if (firstCloudProvider) providers.selectProvider(firstCloudProvider.providerId);
  }, [availableDescriptors, includeLocal, providers]);

  if (providers.isLoading && !providers.editorState) {
    return (
      <div
        className={styles.skeleton}
        aria-label="Loading video providers"
        aria-busy="true"
      >
        <div className={styles.skeletonRail}>
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className={styles.skeletonDetails}>
          <span className={styles.skeletonHeading} />
          <span />
          <span />
          <span />
        </div>
      </div>
    );
  }
  if (!providers.editorState) {
    return (
      <div className={styles.loadError} role="alert">
        <Text variant="body" className={styles.error}>
          {providers.error ?? "Video providers are unavailable."}
        </Text>
        <Button
          hierarchy="secondary"
          label="Try again"
          onClick={() => void providers.refresh().catch(() => undefined)}
        />
      </div>
    );
  }

  const state = providers.editorState;
  const view = getVideoProviderEditorViewModel(state);
  const descriptor = state.snapshot.providers.find(
    (item) => item.providerId === state.selectedProviderId,
  );
  const credentialLabel =
    view.credentialStatus === "stored"
      ? "A credential is already stored. Enter a new value only to replace it."
      : view.credentialRequired
        ? "Required"
        : "Optional for endpoints without authentication";
  const selectedStatus = getProviderStatus(state.selectedProviderId, state.snapshot);
  const endpointHelpId = `video-provider-endpoint-help-${state.selectedProviderId}`;
  const modelHelpId = `video-provider-model-help-${state.selectedProviderId}`;
  const credentialHelpId = `video-provider-credential-help-${state.selectedProviderId}`;

  const handleSave = async () => {
    await providers.save();
    await onSaved?.(state.selectedProviderId);
  };

  return (
    <div className={[styles.editor, className].filter(Boolean).join(" ")}>
      <aside className={styles.providerRail} aria-label="Video providers">
        <div className={styles.railHeader}>
          <Text as="h3" variant="heading" size="xs">
            Providers
          </Text>
          <Text variant="body" size="xs" className={styles.muted}>
            Choose where HyperGen creates your videos.
          </Text>
        </div>
        <div className={styles.providerList}>
          {availableDescriptors.map((item) => {
            const isSelected = item.providerId === state.selectedProviderId;
            const status = getProviderStatus(item.providerId, state.snapshot);
            return (
              <button
                key={item.providerId}
                type="button"
                className={styles.providerOption}
                data-selected={isSelected}
                aria-pressed={isSelected}
                onClick={() => providers.selectProvider(item.providerId)}
              >
                <span className={styles.providerCopy}>
                  <span className={styles.providerName}>{item.displayName}</span>
                  <span className={styles.providerDescription}>
                    {PROVIDER_DESCRIPTIONS[item.providerId]}
                  </span>
                </span>
                <span className={styles.providerStatus} data-tone={status.tone}>
                  <span className={styles.statusDot} aria-hidden="true" />
                  {status.label}
                </span>
              </button>
            );
          })}
        </div>
      </aside>

      <form
        className={styles.details}
        onSubmit={(event) => {
          event.preventDefault();
          if (view.canSubmit && !providers.isSaving) void handleSave();
        }}
      >
        <header className={styles.detailsHeader}>
          <div>
            <Text as="h3" variant="heading" size="sm">
              {view.displayName}
            </Text>
            <Text variant="body" size="sm" className={styles.muted}>
              {PROVIDER_DESCRIPTIONS[state.selectedProviderId]}
            </Text>
          </div>
          <span className={styles.selectedStatus} data-tone={selectedStatus.tone}>
            <span className={styles.statusDot} aria-hidden="true" />
            {selectedStatus.label}
          </span>
        </header>

        <div className={styles.fields}>
          {view.showEndpoint ? (
            <div className={styles.field}>
              <label className={styles.label} htmlFor="video-provider-endpoint">
                Endpoint
              </label>
              <TextField
                id="video-provider-endpoint"
                type="url"
                value={state.baseUrl}
                readOnly={!view.endpointEditable}
                autoComplete="url"
                aria-describedby={endpointHelpId}
                onInputChange={(baseUrl) => providers.updateDraft({ baseUrl })}
              />
              <span className={styles.help} id={endpointHelpId}>
                {view.endpointEditable
                  ? "HTTPS is required for public hosts. Local and private HTTP addresses are supported."
                  : "Managed by this provider."}
              </span>
            </div>
          ) : null}

          {view.showModel ? (
            <div className={styles.field}>
              <label className={styles.label} htmlFor="video-provider-model">
                Model
              </label>
              <TextField
                id="video-provider-model"
                value={state.modelId}
                list={`video-provider-models-${state.selectedProviderId}`}
                aria-describedby={modelHelpId}
                onInputChange={(modelId) => providers.updateDraft({ modelId })}
              />
              <datalist id={`video-provider-models-${state.selectedProviderId}`}>
                {descriptor?.suggestedModelIds.map((modelId) => (
                  <option key={modelId} value={modelId} />
                ))}
              </datalist>
              <span className={styles.help} id={modelHelpId}>
                Choose a suggestion or enter another model ID supported by the provider.
              </span>
            </div>
          ) : null}

          {view.showCredential ? (
            <div className={styles.field}>
              <div className={styles.labelRow}>
                <label className={styles.label} htmlFor="video-provider-api-key">
                  API key
                </label>
                <span className={styles.credentialState}>
                  {view.credentialStatus === "stored"
                    ? "Stored"
                    : view.credentialRequired
                      ? "Required"
                      : "Optional"}
                </span>
              </div>
              <TextField
                id="video-provider-api-key"
                name={`${state.selectedProviderId}-api-key`}
                type="password"
                autoComplete="off"
                value={state.apiKey}
                placeholder={
                  view.credentialStatus === "stored"
                    ? "Enter a new key to replace the stored key"
                    : "Enter API key"
                }
                aria-describedby={credentialHelpId}
                onInputChange={(apiKey) => providers.updateDraft({ apiKey })}
              />
              <span className={styles.help} id={credentialHelpId}>
                {credentialLabel}
              </span>
            </div>
          ) : (
            <div className={styles.localNote}>
              <Text variant="body" size="sm">
                Local generation uses models installed on this device and does not need an
                API key.
              </Text>
            </div>
          )}
        </div>

        <div className={styles.links}>
          {view.signupUrl ? (
            <a href={view.signupUrl} target="_blank" rel="noreferrer">
              Get API key <span aria-hidden="true">↗</span>
            </a>
          ) : null}
          <a href={view.documentationUrl} target="_blank" rel="noreferrer">
            Provider documentation <span aria-hidden="true">↗</span>
          </a>
        </div>

        {providers.error ? (
          <div className={styles.inlineError} role="alert">
            <strong>Could not save this provider.</strong>
            <span>{providers.error}</span>
          </div>
        ) : null}

        <div className={styles.actions}>
          <Button
            type="submit"
            hierarchy="primary"
            label={view.mode === "local" ? "Use local models" : "Test and save"}
            disabled={!view.canSubmit || providers.isSaving}
            isLoading={providers.isSaving}
          />
        </div>
      </form>
    </div>
  );
}
