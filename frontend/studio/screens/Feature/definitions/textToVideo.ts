import type { components } from "../../../../generated/backend-openapi";
import {
  type OfferingId,
  type VideoGenerationAspectRatio,
  type VideoGenerationDuration,
  type VideoGenerationFps,
  type VideoGenerationResolution,
  type VideoOfferingId,
  getProviderVideoOffering,
  isVideoGenerationAspectRatio,
  restoreTextToVideoOfferingId,
  withDefaultTextToVideoOffering,
} from "../../../../lib/video-generation-model-specs.ts";
import { readGenerationParams } from "../../../lib/resultsFeedModel.ts";
import {
  type VideoFeatureContext,
  clampVideoFields,
  isLocalVideoSelectionReady,
  localVideoHasCompatibleOptions,
} from "../../../lib/videoFieldPolicy.ts";
import {
  applyVideoSettingsChange,
  createVideoSettingsOptionFields,
  isSupportedVideoDuration,
  isSupportedVideoFps,
  isSupportedVideoResolution,
} from "../../../lib/videoSettingsControls.ts";
import {
  type FeatureDefinition,
  type FeatureFieldChange,
  type FeatureFormModel,
  type FeatureValues,
  type ValidationIssue,
} from "../types.ts";

type CreateTextToVideoRequest = components["schemas"]["CreateTextToVideoRequest"];

export type TextToVideoSchema = {
  prompt: { kind: "textarea" };
  model: { kind: "options"; value: VideoOfferingId };
  aspectRatio: { kind: "options"; value: VideoGenerationAspectRatio };
  resolution: { kind: "options"; value: VideoGenerationResolution };
  duration: { kind: "options"; value: VideoGenerationDuration };
  fps: { kind: "options"; value: VideoGenerationFps };
  audio: { kind: "options"; value: "off" | "on" };
};

export type TextToVideoValues = FeatureValues<TextToVideoSchema>;

/** Same copy as studio's T2V gallery example — empty-state form seed. */
export const TEXT_TO_VIDEO_EXAMPLE_PROMPT =
  "A dalmatian dog running fast along a sandy beach in dynamic galloping stride, head forward and alert. Soft overcast daylight with cool blue atmospheric tone. Calm water on the left, dense pine forest backdrop, vintage cream and red camper van in distance. Cinematic camera following alongside, shallow depth of field with sharp dog and softer background. Soft hazy lighting with subtle shadows on sand. Wind motion through fur, nostalgic cozy mood. Sound of pounding paws hitting sand rhythmically, wind rushing past, distant gentle waves lapping the shore, muffled forest ambience in the background.";

export const TEXT_TO_VIDEO_DEFAULTS: TextToVideoValues = {
  prompt: TEXT_TO_VIDEO_EXAMPLE_PROMPT,
  model: "ltx-2.5-fast",
  aspectRatio: "16:9",
  resolution: "540p",
  duration: 8,
  fps: 24,
  audio: "off",
};

export function seedTextToVideoValues(context: VideoFeatureContext): TextToVideoValues {
  return withDefaultTextToVideoOffering(context.specs, TEXT_TO_VIDEO_DEFAULTS);
}

export function fromGeneration(
  spec: unknown,
  context?: VideoFeatureContext,
): TextToVideoValues | null {
  const params = readGenerationParams(spec);
  if (!params || typeof params.prompt !== "string") return null;

  return {
    prompt: params.prompt,
    model:
      restoreTextToVideoOfferingId(params.model, context?.specs) ??
      TEXT_TO_VIDEO_DEFAULTS.model,
    aspectRatio: isVideoGenerationAspectRatio(params.aspectRatio)
      ? params.aspectRatio
      : TEXT_TO_VIDEO_DEFAULTS.aspectRatio,
    resolution: isSupportedVideoResolution(params.resolution)
      ? params.resolution
      : TEXT_TO_VIDEO_DEFAULTS.resolution,
    duration: isSupportedVideoDuration(params.duration)
      ? params.duration
      : TEXT_TO_VIDEO_DEFAULTS.duration,
    fps: isSupportedVideoFps(params.fps) ? params.fps : TEXT_TO_VIDEO_DEFAULTS.fps,
    audio: params.audio === true ? "on" : "off",
  };
}

export function validateTextToVideo(values: TextToVideoValues): ValidationIssue[] {
  if (values.prompt.trim().length === 0) {
    return [
      {
        id: "prompt-required",
        fieldId: "prompt",
        message: "Prompt is required.",
      },
    ];
  }
  return [];
}

export function toCreateBody(values: TextToVideoValues): CreateTextToVideoRequest {
  const separator = values.model.indexOf(":");
  const provider =
    separator > 0
      ? {
          providerId: values.model.slice(0, separator),
          modelId: values.model.slice(separator + 1),
        }
      : null;
  return {
    contract_version: provider ? 2 : 1,
    ...(provider ? { provider } : {}),
    params: {
      prompt: values.prompt.trim(),
      // The v1 params envelope keeps its local offering discriminator for backward
      // compatibility. Cloud identity lives in the v2 provider target above.
      model: provider
        ? ("ltx-2.5-fast" satisfies OfferingId)
        : (values.model as OfferingId),
      aspectRatio: values.aspectRatio,
      resolution: values.resolution,
      duration: values.duration,
      fps: values.fps,
      audio: values.audio === "on",
      cameraMotion: "none",
      negativePrompt: "",
      loras: [],
      promptProvenance: "typed",
    },
  };
}

export function buildTextToVideoForm(
  values: TextToVideoValues,
  context: VideoFeatureContext,
): FeatureFormModel<TextToVideoSchema> {
  const providerOffering = getProviderVideoOffering(context.specs, values.model);
  const settingsFields = createVideoSettingsOptionFields<TextToVideoSchema>(
    values,
    context.specs,
    { includeProvider: true },
  );
  const controls = providerOffering?.controls;
  const visibleSettings: FeatureFormModel<TextToVideoSchema>["fields"] = controls
    ? settingsFields.filter(
        (field) => field.dataKey === "model" || controls[field.dataKey] === "editable",
      )
    : settingsFields;
  if (controls?.audio === "optional") {
    visibleSettings.push({
      kind: "options",
      id: "audio",
      label: "Audio",
      dataKey: "audio",
      options: [
        { value: "off", label: "Off" },
        { value: "on", label: "On" },
      ],
    });
  }
  return {
    fields: [
      {
        kind: "textarea",
        id: "prompt",
        label: "Prompt",
        dataKey: "prompt",
        placeholder: "The woman sips from a cup of coffee...",
      },
      ...visibleSettings,
    ],
  };
}

export function applyTextToVideoChange(
  values: TextToVideoValues,
  change: FeatureFieldChange<TextToVideoSchema>,
  context: VideoFeatureContext,
): TextToVideoValues {
  if (change.dataKey === "audio") {
    return { ...values, audio: change.value };
  }
  return applyVideoSettingsChange<TextToVideoSchema>(
    values,
    change,
    context.specs,
    withDefaultTextToVideoOffering(context.specs, TEXT_TO_VIDEO_DEFAULTS),
  );
}

function normalizeTextToVideo(
  values: TextToVideoValues,
  context: VideoFeatureContext,
): TextToVideoValues {
  const clamped = clampVideoFields(
    values,
    context.specs,
    withDefaultTextToVideoOffering(context.specs, TEXT_TO_VIDEO_DEFAULTS),
  );
  const providerOffering = getProviderVideoOffering(context.specs, clamped.model);
  const controls = providerOffering?.controls;
  if (!controls) return { ...clamped, audio: clamped.audio ?? "off" };
  return {
    ...clamped,
    fps: controls.fps === "editable" ? clamped.fps : 24,
    audio:
      controls.audio === "required"
        ? "on"
        : controls.audio === "unsupported"
          ? "off"
          : (clamped.audio ?? "off"),
  };
}

export const textToVideoDefinition: FeatureDefinition<
  TextToVideoSchema,
  CreateTextToVideoRequest,
  VideoFeatureContext,
  "text-to-video"
> = {
  id: "text-to-video",
  title: "Text to Video",
  defaults: TEXT_TO_VIDEO_DEFAULTS,
  initialValues: seedTextToVideoValues,
  resetValues: seedTextToVideoValues,
  form: buildTextToVideoForm,
  applyChange: applyTextToVideoChange,
  normalize: normalizeTextToVideo,
  fromGeneration,
  validate: validateTextToVideo,
  toCreateBody,
  isReady: (values, context) => isLocalVideoSelectionReady(values, context.specs),
  isUnavailable: (values, context) =>
    !localVideoHasCompatibleOptions(values, context.specs),
};
