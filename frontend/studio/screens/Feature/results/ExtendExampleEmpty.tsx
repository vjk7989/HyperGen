import { packagedExploreExampleUrl } from "../../../assets/packaged-explore-assets";

import { ExampleEmptyMedia } from "./ExampleEmptyMedia";

export function ExtendExampleEmpty() {
  return (
    <ExampleEmptyMedia
      posterUrl={packagedExploreExampleUrl("extend-example-poster")}
      videoUrl={packagedExploreExampleUrl("extend-example-video")}
    />
  );
}
