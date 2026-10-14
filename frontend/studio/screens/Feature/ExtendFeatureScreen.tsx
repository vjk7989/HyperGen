import {
  EXTEND_SEED_REVISION,
  isPackagedExtendSeedName,
  planExtendSeed,
  readAppliedExtendSeedRevision,
  writeAppliedExtendSeedRevision,
} from "../../hooks/extendSeed.ts";
import { useCreateExtend } from "../../hooks/useCreateExtend";
import { useExtendSeed } from "../../hooks/useExtendSeed";

import { extendFormPresentation } from "./ExtendFormPresentation";
import { VideoToVideoFeatureScreen } from "./VideoToVideoFeatureScreen";
import { extendDefinition, seedExtendValues } from "./definitions/extend";
import { ExtendExampleEmpty } from "./results/ExtendExampleEmpty";

export function ExtendFeatureScreen() {
  const createGeneration = useCreateExtend();
  return (
    <VideoToVideoFeatureScreen
      featureId="extend"
      definition={extendDefinition}
      presentation={extendFormPresentation}
      EmptyStateAdapter={ExtendExampleEmpty}
      createGeneration={createGeneration}
      useSeed={useExtendSeed}
      planSeed={(input) =>
        planExtendSeed({
          ...input,
          appliedSeedRevision: readAppliedExtendSeedRevision(),
          packagedSeedRevision: EXTEND_SEED_REVISION,
        })
      }
      isPackagedSeedName={isPackagedExtendSeedName}
      writeAppliedRevision={() => writeAppliedExtendSeedRevision(EXTEND_SEED_REVISION)}
      seedValues={seedExtendValues}
    />
  );
}
