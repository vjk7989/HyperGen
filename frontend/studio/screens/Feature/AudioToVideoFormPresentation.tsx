import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { AudioToVideoSchema } from "./definitions/audioToVideo";
import { orderVideoSettingsOptionFields } from "./fields/optionControlPresentation";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";

export const audioToVideoFormPresentation: FeatureFormPresentationAdapter<AudioToVideoSchema> =
  {
    getOptionIcon: getVideoOptionIcon,
    orderOptionFields: orderVideoSettingsOptionFields,
  };
