import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { TextToVideoSchema } from "./definitions/textToVideo";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";
import { orderTextToVideoOptionFields } from "./textToVideoOptionFieldOrder";

export const textToVideoFormPresentation: FeatureFormPresentationAdapter<TextToVideoSchema> =
  {
    getOptionIcon: getVideoOptionIcon,
    orderOptionFields: orderTextToVideoOptionFields,
  };
