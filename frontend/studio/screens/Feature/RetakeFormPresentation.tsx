import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { RetakeSchema } from "./definitions/retake";
import { orderVideoSettingsOptionFields } from "./fields/optionControlPresentation";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";

export const retakeFormPresentation: FeatureFormPresentationAdapter<RetakeSchema> = {
  getOptionIcon: getVideoOptionIcon,
  orderOptionFields: orderVideoSettingsOptionFields,
};
