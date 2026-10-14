import { useQuery } from "@tanstack/react-query";

import { useExploreRuntime } from "../runtime/ExploreRuntime";

import {
  VIDEO_GENERATION_MODEL_SPECS_QUERY_OPTIONS,
  fetchVideoGenerationModelSpecs,
  generationQueryKeys,
} from "./generationQueryKeys";

export function useVideoGenerationModelSpecs() {
  const { api, modelsVersion } = useExploreRuntime();
  return useQuery({
    queryKey: generationQueryKeys.specs(modelsVersion),
    queryFn: () => fetchVideoGenerationModelSpecs(api),
    ...VIDEO_GENERATION_MODEL_SPECS_QUERY_OPTIONS,
  });
}
