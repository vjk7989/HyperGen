import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { IcLoraRecipeSchema } from "./definitions/icLoraRecipe";
import { orderVideoSettingsOptionFields } from "./fields/optionControlPresentation";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";

export const icLoraRecipeFormPresentation: FeatureFormPresentationAdapter<IcLoraRecipeSchema> =
  {
    getOptionIcon: getVideoOptionIcon,
    orderOptionFields: orderVideoSettingsOptionFields,
    naturalImagePreview: true,
  };
