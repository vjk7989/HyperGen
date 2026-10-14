import { createRemoteExploreRuntime } from "../../remote/remote-explore-runtime.ts";

import type { ExploreRuntime } from "./ExploreRuntime.ts";
import { createDesktopExploreRuntime } from "./createDesktopExploreRuntime.ts";
import {
  DESKTOP_GENERATION_POLLING_POLICY,
  type ExploreGenerationPollingPolicy,
  REMOTE_GENERATION_POLLING_POLICY,
} from "./generationPollingPolicy.ts";

type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;

const runtimeHasPolicy: Expect<
  Equal<ExploreRuntime["generationPolling"], ExploreGenerationPollingPolicy>
> = true;
const desktopPolicy: Expect<
  Equal<
    ReturnType<typeof createDesktopExploreRuntime>["generationPolling"],
    ExploreGenerationPollingPolicy
  >
> = true;
const remotePolicy: Expect<
  Equal<
    ReturnType<typeof createRemoteExploreRuntime>["generationPolling"],
    ExploreGenerationPollingPolicy
  >
> = true;
const desktopIntervalIsNumber: Expect<
  Equal<(typeof DESKTOP_GENERATION_POLLING_POLICY)["queueActiveIntervalMs"], number>
> = true;
const remoteIntervalIsNumber: Expect<
  Equal<(typeof REMOTE_GENERATION_POLLING_POLICY)["queueActiveIntervalMs"], number>
> = true;

void [
  runtimeHasPolicy,
  desktopPolicy,
  remotePolicy,
  desktopIntervalIsNumber,
  remoteIntervalIsNumber,
];
