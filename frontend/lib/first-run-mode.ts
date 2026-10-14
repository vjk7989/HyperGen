export type FirstRunMode = "local" | "api" | "explore";

export interface FirstRunModePlanInput {
  mode: FirstRunMode;
  activeProviderId: string;
  activeProviderConfigured: boolean;
  local: {
    huggingFaceAuthenticated: boolean;
    modelAccessGranted: boolean;
    localDownloadsRequired: boolean;
  };
}

export interface FirstRunModePlan {
  mode: FirstRunMode;
  action:
    | "complete"
    | "configure-provider"
    | "authenticate-hugging-face"
    | "request-model-access"
    | "download-local-models";
  blocker:
    | "provider-configuration"
    | "hugging-face-authentication"
    | "model-access"
    | null;
  shouldStartLocalDownloads: boolean;
}

export function resolveFirstRunModePlan(input: FirstRunModePlanInput): FirstRunModePlan {
  if (input.mode === "explore") {
    return {
      mode: "explore",
      action: "complete",
      blocker: null,
      shouldStartLocalDownloads: false,
    };
  }

  if (input.mode === "api") {
    const configured =
      input.activeProviderId !== "local" && input.activeProviderConfigured;
    return configured
      ? {
          mode: "api",
          action: "complete",
          blocker: null,
          shouldStartLocalDownloads: false,
        }
      : {
          mode: "api",
          action: "configure-provider",
          blocker: "provider-configuration",
          shouldStartLocalDownloads: false,
        };
  }

  if (!input.local.localDownloadsRequired) {
    return {
      mode: "local",
      action: "complete",
      blocker: null,
      shouldStartLocalDownloads: false,
    };
  }
  if (!input.local.huggingFaceAuthenticated) {
    return {
      mode: "local",
      action: "authenticate-hugging-face",
      blocker: "hugging-face-authentication",
      shouldStartLocalDownloads: false,
    };
  }
  if (!input.local.modelAccessGranted) {
    return {
      mode: "local",
      action: "request-model-access",
      blocker: "model-access",
      shouldStartLocalDownloads: false,
    };
  }
  return {
    mode: "local",
    action: "download-local-models",
    blocker: null,
    shouldStartLocalDownloads: true,
  };
}
