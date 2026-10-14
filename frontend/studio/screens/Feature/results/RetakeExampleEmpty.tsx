import { packagedExploreExampleUrl } from "../../../assets/packaged-explore-assets";

import { ExampleEmptyMedia } from "./ExampleEmptyMedia";

export function RetakeExampleEmpty() {
  return (
    <ExampleEmptyMedia
      posterUrl={packagedExploreExampleUrl("retake-example-poster")}
      videoUrl={packagedExploreExampleUrl("retake-example-video")}
    />
  );
}
