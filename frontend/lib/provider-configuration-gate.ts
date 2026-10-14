export type ApiGatewayKind = "api-keys" | "video-provider";
export type ProviderConfigurationStatus =
  | "idle"
  | "validating"
  | "saving"
  | "activating"
  | "succeeded"
  | "error";

export function resolveApiGatewayPlan(input: {
  kind: ApiGatewayKind;
  blocking: boolean;
  requiredKeys: readonly ("ltx" | "fal")[];
}): {
  content: "legacy-api-keys" | "video-provider-editor";
  legacyKeySections: ("ltx" | "fal")[];
  blocking: boolean;
} {
  if (input.kind === "video-provider") {
    return {
      content: "video-provider-editor",
      legacyKeySections: [],
      blocking: input.blocking,
    };
  }
  return {
    content: "legacy-api-keys",
    legacyKeySections: input.requiredKeys.filter(
      (key): key is "ltx" | "fal" => key === "ltx" || key === "fal",
    ),
    blocking: input.blocking,
  };
}

export function shouldCloseProviderConfiguration(
  status: ProviderConfigurationStatus,
): boolean {
  return status === "succeeded";
}

export function canDismissProviderConfiguration(input: {
  blocking: boolean;
  configurationSucceeded: boolean;
}): boolean {
  void input;
  return true;
}

export type GenerationPreflightResult =
  | { kind: "ready" }
  | { kind: "configure-provider"; providerId: string }
  | { kind: "configure-local" }
  | { kind: "status-error" };

export function resolveGenerationPreflight(input: {
  providerStatus: "ready" | "error";
  localInstallationViable: boolean;
  activeProviderId: string;
  activeProviderConfigured: boolean;
}): GenerationPreflightResult {
  if (input.providerStatus === "error") return { kind: "status-error" };
  if (input.activeProviderId === "local") {
    return input.localInstallationViable
      ? { kind: "ready" }
      : { kind: "configure-local" };
  }
  return input.activeProviderConfigured
    ? { kind: "ready" }
    : { kind: "configure-provider", providerId: input.activeProviderId };
}

export function shouldAutomaticallySubmitAfterProviderConfiguration(
  status: ProviderConfigurationStatus,
): boolean {
  void status;
  return false;
}

export function isActiveVideoProviderConfigured(snapshot: {
  activeProvider: string;
  profiles: readonly {
    providerId: string;
    baseUrl?: string | null;
    modelId?: string | null;
    hasApiKey: boolean;
  }[];
}): boolean {
  if (snapshot.activeProvider === "local") return false;
  const profile = snapshot.profiles.find(
    (item) => item.providerId === snapshot.activeProvider,
  );
  return Boolean(
    profile?.baseUrl &&
      profile.modelId &&
      (profile.providerId === "custom" || profile.hasApiKey),
  );
}
