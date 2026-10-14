from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


ProviderId = Literal[
    "local",
    "ltx",
    "fal",
    "replicate",
    "runway",
    "luma",
    "google_veo",
    "custom",
]

PROVIDER_IDS: tuple[ProviderId, ...] = (
    "local",
    "ltx",
    "fal",
    "replicate",
    "runway",
    "luma",
    "google_veo",
    "custom",
)


def _to_camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class _PublicModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel_case,
        populate_by_name=True,
        frozen=True,
    )


class ProviderCapabilities(_PublicModel):
    text_to_video: bool = True


ProviderControlMode = Literal[
    "editable",
    "unsupported",
    "fixed",
    "optional",
    "required",
]


class ProviderVideoControls(_PublicModel):
    aspect_ratio: ProviderControlMode = "editable"
    resolution: ProviderControlMode = "editable"
    duration: ProviderControlMode = "editable"
    fps: ProviderControlMode = "editable"
    audio: ProviderControlMode = "optional"


class ProviderDescriptor(_PublicModel):
    provider_id: ProviderId
    display_name: str
    default_base_url: str | None
    signup_url: str | None
    documentation_url: str
    suggested_model_ids: tuple[str, ...] = ()
    capabilities: ProviderCapabilities = ProviderCapabilities()
    controls: ProviderVideoControls = ProviderVideoControls()


class PublicProviderProfile(_PublicModel):
    provider_id: ProviderId
    base_url: str | None = None
    model_id: str | None = None
    has_api_key: bool = False


class ProviderProfile(_PublicModel):
    provider_id: ProviderId
    base_url: str | None = None
    model_id: str | None = None
    api_key: str | None = None

    @field_validator("base_url", "model_id", "api_key", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    def to_public(self) -> PublicProviderProfile:
        return PublicProviderProfile(
            provider_id=self.provider_id,
            base_url=self.base_url,
            model_id=self.model_id,
            has_api_key=self.api_key is not None,
        )


class ProviderTextToVideoRequest(_PublicModel):
    prompt: str
    model_id: str
    aspect_ratio: str
    resolution: str
    duration: int | float | None
    fps: int | float
    generate_audio: bool = False
    negative_prompt: str = ""
    seed: int | None = None
