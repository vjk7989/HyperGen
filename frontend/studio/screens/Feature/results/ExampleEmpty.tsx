import { packagedExploreExampleUrl } from "../../../assets/packaged-explore-assets";

import { ExampleEmptyMedia } from "./ExampleEmptyMedia";

export function ExampleEmpty() {
  return (
    <ExampleEmptyMedia
      posterUrl={packagedExploreExampleUrl("text-to-video-example-poster")}
      videoUrl={packagedExploreExampleUrl("text-to-video-example-video")}
    />
  );
}
