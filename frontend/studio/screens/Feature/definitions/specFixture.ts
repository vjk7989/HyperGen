import type { VideoGenerationModelSpecsResponse } from "../../../../lib/video-generation-model-specs";

type LocalSpec = VideoGenerationModelSpecsResponse["local_models"][number]["spec"];
type ResolutionCell = LocalSpec["supported_resolutions_durations"][string];

const LOCAL_ASPECTS = ["21:9", "16:9", "3:2", "4:3", "1:1", "4:5", "9:16"] as const;
const LOCAL_FPS = ["24", "25", "48", "50"] as const;

function cell(
  durations: ResolutionCell["fps_to_durations"][string],
  aspectRatios: ResolutionCell["aspect_ratios"],
): ResolutionCell {
  return {
    fps_to_durations: Object.fromEntries(LOCAL_FPS.map((fps) => [fps, [...durations]])),
    aspect_ratios: aspectRatios,
  };
}

function localSpec(displayName: string): LocalSpec {
  return {
    display_name: displayName,
    supported_resolutions_durations: {
      "540p": cell([2, 3, 4, 5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "720p": cell([2, 3, 4, 5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "1080p": cell([2, 3, 4, 5, 10], [...LOCAL_ASPECTS]),
    },
    a2v_supported_resolutions_durations: {
      "270p": cell([5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "360p": cell([5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "540p": cell([5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "720p": cell([5, 6, 8, 10, 20], [...LOCAL_ASPECTS]),
      "1080p": cell([5, 10], [...LOCAL_ASPECTS]),
    },
  };
}

const LTX_25_FAST_SPEC = localSpec("LTX 2.5 Fast");
const LTX_23_FAST_SPEC = localSpec("LTX 2.3 Fast");

/** Mirrors the backend LOCAL catalog shape for tests. */
export function specFixture(): VideoGenerationModelSpecsResponse {
  return {
    api_models: [],
    local_models: [
      {
        pipeline: "fast",
        spec: LTX_25_FAST_SPEC,
      },
    ],
    downloaded_local_models: [
      {
        model: "ltx-2.5-fast",
        pipeline: "fast",
        spec: LTX_25_FAST_SPEC,
      },
    ],
    active_offering: "ltx-2.5-fast",
    low_performance_machine: false,
  };
}

export function specFixtureBothOfferings(
  activeDisplayName: "LTX 2.5 Fast" | "LTX 2.3 Fast" = "LTX 2.3 Fast",
): VideoGenerationModelSpecsResponse {
  const activeSpec =
    activeDisplayName === "LTX 2.3 Fast" ? LTX_23_FAST_SPEC : LTX_25_FAST_SPEC;
  return {
    api_models: [],
    local_models: [{ pipeline: "fast", spec: activeSpec }],
    downloaded_local_models: [
      {
        model: "ltx-2.5-fast",
        pipeline: "fast",
        spec: LTX_25_FAST_SPEC,
      },
      {
        model: "ltx-2.3-fast",
        pipeline: "fast",
        spec: LTX_23_FAST_SPEC,
      },
    ],
    active_offering:
      activeDisplayName === "LTX 2.3 Fast" ? "ltx-2.3-fast" : "ltx-2.5-fast",
    low_performance_machine: false,
  };
}

export const OPAQUE_FAL_OFFERING_ID = "fal:team/opaque-video@2026.10";
export const SUGGESTED_FAL_OFFERING_ID =
  "fal:fal-ai/kling-video/v3/standard/text-to-video";

export type ProviderControlMode =
  | "editable"
  | "unsupported"
  | "fixed"
  | "optional"
  | "required";

export const PROVIDER_CONTROL_CAPABILITIES = {
  fal: {
    aspectRatio: "editable",
    resolution: "unsupported",
    duration: "editable",
    fps: "unsupported",
    audio: "optional",
  },
  replicate: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "unsupported",
    audio: "optional",
  },
  runway: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "unsupported",
    audio: "unsupported",
  },
  luma: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "unsupported",
    audio: "unsupported",
  },
  google_veo: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "fixed",
    audio: "required",
  },
  ltx: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "editable",
    audio: "optional",
  },
  custom: {
    aspectRatio: "editable",
    resolution: "editable",
    duration: "editable",
    fps: "editable",
    audio: "optional",
  },
} as const satisfies Record<
  string,
  Record<"aspectRatio" | "resolution" | "duration" | "fps" | "audio", ProviderControlMode>
>;

export type ProviderControlFixtureId = keyof typeof PROVIDER_CONTROL_CAPABILITIES;

/** One active cloud offering for provider-control form tests. */
export function specFixtureProviderControls(
  providerId: ProviderControlFixtureId,
): VideoGenerationModelSpecsResponse {
  const offeringId = `${providerId}:test/video-model`;
  return {
    api_models: [],
    local_models: [],
    downloaded_local_models: [],
    active_offering: offeringId,
    low_performance_machine: false,
    providerOfferings: [
      {
        providerId,
        modelId: "test/video-model",
        offeringId,
        displayName: `${providerId} test model`,
        capabilities: { textToVideo: true },
        controls: PROVIDER_CONTROL_CAPABILITIES[providerId],
        optionMatrix: {
          "1080p": {
            aspectRatios: ["16:9", "9:16"],
            fpsToDurations: { "24": [5, 8], "50": [10] },
          },
        },
      },
    ],
  } as unknown as VideoGenerationModelSpecsResponse;
}

/** Active cloud-provider fixture with per-offering option matrices. */
export function specFixtureProviderOfferings(): VideoGenerationModelSpecsResponse {
  return {
    api_models: [],
    local_models: [],
    downloaded_local_models: [],
    active_offering: OPAQUE_FAL_OFFERING_ID,
    low_performance_machine: false,
    providerOfferings: [
      {
        providerId: "fal",
        modelId: "team/opaque-video@2026.10",
        offeringId: OPAQUE_FAL_OFFERING_ID,
        displayName: "fal.ai · team/opaque-video@2026.10",
        capabilities: { textToVideo: true },
        optionMatrix: {
          "1080p": {
            aspectRatios: ["16:9"],
            fpsToDurations: { "50": [10] },
          },
        },
      },
      {
        providerId: "fal",
        modelId: "fal-ai/kling-video/v3/standard/text-to-video",
        offeringId: SUGGESTED_FAL_OFFERING_ID,
        displayName: "fal.ai · Kling Video v3 Standard",
        capabilities: { textToVideo: true },
        optionMatrix: {
          "720p": {
            aspectRatios: ["16:9", "9:16"],
            fpsToDurations: { "24": [5] },
          },
        },
      },
    ],
  } as unknown as VideoGenerationModelSpecsResponse;
}
