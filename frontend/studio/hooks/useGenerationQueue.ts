import { useQuery } from "@tanstack/react-query";

import {
  type ExploreGenerationPollingPolicy,
  GENERATION_POLLING_QUERY_OPTIONS,
  type QueuePollQueryState,
  queueRefetchInterval,
} from "../runtime/generationPollingPolicy.ts";

import {
  type GenerationQueueApi,
  fetchGenerationQueue,
  generationQueryKeys,
} from "./generationQueryKeys.ts";

export type UseGenerationQueueOptions = {
  api: GenerationQueueApi;
  generationPolling: ExploreGenerationPollingPolicy;
  isLive: boolean;
};

export function generationQueueQueryOptions({
  api,
  generationPolling,
  isLive,
}: UseGenerationQueueOptions) {
  return {
    queryKey: generationQueryKeys.queue,
    queryFn: () => fetchGenerationQueue(api),
    enabled: true,
    ...GENERATION_POLLING_QUERY_OPTIONS,
    refetchInterval: (query: { state: QueuePollQueryState }) =>
      queueRefetchInterval(
        generationPolling,
        {
          data: query.state.data,
          error: query.state.error,
          fetchFailureCount: query.state.fetchFailureCount,
        },
        isLive,
      ),
  };
}

export function useGenerationQueue(options: UseGenerationQueueOptions) {
  return useQuery(generationQueueQueryOptions(options));
}
