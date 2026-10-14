import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { ExtendSchema } from "./definitions/extend";
import { orderVideoSettingsOptionFields } from "./fields/optionControlPresentation";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";

export const extendFormPresentation: FeatureFormPresentationAdapter<ExtendSchema> = {
  getOptionIcon: getVideoOptionIcon,
  orderOptionFields: orderVideoSettingsOptionFields,
};
