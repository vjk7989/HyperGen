from __future__ import annotations

from services.video_providers.models import (
    PROVIDER_IDS,
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderVideoControls,
)


_T2V = ProviderCapabilities()

PROVIDER_DESCRIPTORS: dict[str, ProviderDescriptor] = {
    descriptor.provider_id: descriptor
    for descriptor in (
        ProviderDescriptor(
            provider_id="local",
            display_name="Local models",
            default_base_url=None,
            signup_url=None,
            documentation_url="https://github.com/vjk7989/HyperGen#local-models",
            suggested_model_ids=("Lightricks/LTX-Video-0.9.8-13B-distilled",),
            capabilities=_T2V,
        ),
        ProviderDescriptor(
            provider_id="ltx",
            display_name="LTX API",
            default_base_url="https://api.ltx.io",
            signup_url="https://console.ltx.io/",
            documentation_url="https://docs.ltx.io/quickstart",
            suggested_model_ids=("ltx-2-5-fast", "ltx-2-5-pro"),
            capabilities=_T2V,
        ),
        ProviderDescriptor(
            provider_id="fal",
            display_name="fal.ai",
            default_base_url="https://queue.fal.run",
            signup_url="https://fal.ai/dashboard/keys",
            documentation_url="https://docs.fal.ai/",
            suggested_model_ids=(
                "fal-ai/kling-video/v3/4k/text-to-video",
                "fal-ai/kling-video/v3/standard/text-to-video",
            ),
            capabilities=_T2V,
            controls=ProviderVideoControls(
                resolution="unsupported",
                fps="unsupported",
            ),
        ),
        ProviderDescriptor(
            provider_id="replicate",
            display_name="Replicate",
            default_base_url="https://api.replicate.com/v1",
            signup_url="https://replicate.com/account/api-tokens",
            documentation_url="https://replicate.com/docs/reference/http/",
            suggested_model_ids=(
                "bytedance/seedance-2.0-fast",
                "bytedance/seedance-2.0",
            ),
            capabilities=_T2V,
            controls=ProviderVideoControls(fps="unsupported"),
        ),
        ProviderDescriptor(
            provider_id="runway",
            display_name="Runway",
            default_base_url="https://api.dev.runwayml.com/v1",
            signup_url="https://dev.runwayml.com/",
            documentation_url="https://docs.dev.runwayml.com/",
            suggested_model_ids=("gen4.5",),
            capabilities=_T2V,
            controls=ProviderVideoControls(fps="unsupported", audio="unsupported"),
        ),
        ProviderDescriptor(
            provider_id="luma",
            display_name="Luma Dream Machine",
            default_base_url="https://api.lumalabs.ai/dream-machine/v1",
            signup_url="https://platform.lumalabs.ai/",
            documentation_url="https://docs.lumalabs.ai/reference/creategeneration",
            suggested_model_ids=("ray-flash-2", "ray-2"),
            capabilities=_T2V,
            controls=ProviderVideoControls(fps="unsupported", audio="unsupported"),
        ),
        ProviderDescriptor(
            provider_id="google_veo",
            display_name="Google Veo",
            default_base_url="https://generativelanguage.googleapis.com/v1beta",
            signup_url="https://aistudio.google.com/app/apikey",
            documentation_url="https://ai.google.dev/gemini-api/docs/veo",
            suggested_model_ids=(
                "veo-3.1-fast-generate-preview",
                "veo-3.1-generate-preview",
            ),
            capabilities=_T2V,
            controls=ProviderVideoControls(fps="fixed", audio="required"),
        ),
        ProviderDescriptor(
            provider_id="custom",
            display_name="Custom endpoint",
            default_base_url=None,
            signup_url=None,
            documentation_url=(
                "https://github.com/vjk7989/HyperGen/blob/main/docs/custom-provider.md"
            ),
            suggested_model_ids=(),
            capabilities=_T2V,
        ),
    )
}

assert tuple(PROVIDER_DESCRIPTORS) == PROVIDER_IDS
