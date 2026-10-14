import type { FeatureFormPresentationAdapter } from "./FeatureFormView";
import type { LoraRecipeSchema } from "./definitions/loraRecipe";
import { orderVideoSettingsOptionFields } from "./fields/optionControlPresentation";
import { getVideoOptionIcon } from "./fields/videoOptionIcons";

export const loraRecipeFormPresentation: FeatureFormPresentationAdapter<LoraRecipeSchema> =
  {
    getOptionIcon: getVideoOptionIcon,
    orderOptionFields: (fields) => orderVideoSettingsOptionFields(fields),
  };
