from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from services.video_providers import (
    PROVIDER_DESCRIPTORS,
    PROVIDER_IDS,
    ProviderDescriptor,
    ProviderError,
    ProviderProfile,
    PublicProviderProfile,
)
from services.video_providers.persistence import ProviderProfileStore


def _to_camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class _APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel_case, populate_by_name=True)


class ProviderProfileUpdate(_APIModel):
    base_url: str | None = None
    model_id: str | None = None
    api_key: str | None = None


class ActiveProviderUpdate(_APIModel):
    provider_id: str


class ActiveProviderResponse(_APIModel):
    active_provider: str


class ProviderValidationResponse(_APIModel):
    provider_id: str
    valid: bool
    validation_mode: str


class VideoProviderSnapshot(_APIModel):
    active_provider: str
    providers: list[ProviderDescriptor]
    profiles: list[PublicProviderProfile]


_CLOUD_PROVIDER_IDS = frozenset(
    {"ltx", "fal", "replicate", "runway", "luma", "google_veo"}
)


class VideoProviderHandler:
    def __init__(self, store: ProviderProfileStore) -> None:
        self._store = store

    def get_snapshot(self) -> VideoProviderSnapshot:
        return VideoProviderSnapshot(
            active_provider=self._store.active_provider,
            providers=list(PROVIDER_DESCRIPTORS.values()),
            profiles=[profile.to_public() for profile in self._store.list_profiles()],
        )

    def update_profile(
        self, provider_id: str, update: ProviderProfileUpdate
    ) -> PublicProviderProfile:
        profile = self._profile_from_update(provider_id, update)
        if provider_id == "custom":
            self._validate_custom_profile(profile)
        self._store.save_profile(profile)
        return profile.to_public()

    def set_active_provider(self, provider_id: str) -> ActiveProviderResponse:
        self._descriptor(provider_id)
        if provider_id in _CLOUD_PROVIDER_IDS:
            self._require_credential(provider_id)
        if provider_id == "custom":
            profile = self._store.get_profile(provider_id)
            if profile is None:
                raise ProviderError(
                    code="PROVIDER_CONFIGURATION_INVALID",
                    provider=provider_id,
                    message="Configure the custom video provider before selecting it",
                )
            self._validate_custom_profile(profile)
        self._store.set_active_provider(provider_id)
        return ActiveProviderResponse(active_provider=provider_id)

    def validate(
        self, provider_id: str, update: ProviderProfileUpdate | None = None
    ) -> ProviderValidationResponse:
        self._descriptor(provider_id)
        if provider_id == "local":
            return ProviderValidationResponse(
                provider_id=provider_id, valid=True, validation_mode="local"
            )
        profile = (
            self._profile_from_update(provider_id, update)
            if update is not None
            else self._store.get_profile(provider_id)
        )
        if provider_id in _CLOUD_PROVIDER_IDS:
            self._require_credential(provider_id, profile)
        if provider_id == "custom":
            if profile is None:
                raise ProviderError(
                    code="PROVIDER_CONFIGURATION_INVALID",
                    provider=provider_id,
                    message="Configure the custom video provider before validating it",
                )
            self._validate_custom_profile(profile)
        return ProviderValidationResponse(
            provider_id=provider_id, valid=True, validation_mode="configuration"
        )

    def _profile_from_update(
        self, provider_id: str, update: ProviderProfileUpdate
    ) -> ProviderProfile:
        descriptor = self._descriptor(provider_id)
        existing = self._store.get_profile(provider_id)
        return ProviderProfile(
            provider_id=descriptor.provider_id,
            base_url=self._updated_value(
                update,
                "base_url",
                existing.base_url if existing else descriptor.default_base_url,
            ),
            model_id=self._updated_value(
                update,
                "model_id",
                existing.model_id
                if existing
                else next(iter(descriptor.suggested_model_ids), None),
            ),
            api_key=self._updated_value(
                update, "api_key", existing.api_key if existing else None
            ),
        )

    @staticmethod
    def _updated_value(
        update: ProviderProfileUpdate, field: str, fallback: str | None
    ) -> str | None:
        if field not in update.model_fields_set:
            return fallback
        value = getattr(update, field)
        if isinstance(value, str):
            value = value.strip()
        return value or None

    @staticmethod
    def _descriptor(provider_id: str):
        if provider_id not in PROVIDER_IDS:
            raise ProviderError(
                code="PROVIDER_NOT_FOUND",
                provider=provider_id,
                message=f"Unknown video provider: {provider_id}",
            )
        return PROVIDER_DESCRIPTORS[provider_id]

    def _require_credential(
        self, provider_id: str, profile: ProviderProfile | None = None
    ) -> None:
        if profile is None:
            profile = self._store.get_profile(provider_id)
        if profile is None or profile.api_key is None:
            raise ProviderError(
                code="PROVIDER_CREDENTIAL_REQUIRED",
                provider=provider_id,
                message=f"An API key is required for {provider_id}",
            )

    @staticmethod
    def _validate_custom_profile(profile: ProviderProfile) -> None:
        if profile.base_url is None or profile.model_id is None:
            raise ProviderError(
                code="PROVIDER_CONFIGURATION_INVALID",
                provider="custom",
                message="Custom providers require a base URL and model ID",
            )
        parsed = urlparse(profile.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProviderError(
                code="PROVIDER_URL_UNSAFE",
                provider="custom",
                message="Custom provider URL must be a valid HTTP or HTTPS URL",
            )
        if parsed.scheme == "https":
            return
        hostname = parsed.hostname.lower()
        is_private = hostname == "localhost"
        try:
            address = ipaddress.ip_address(hostname)
            is_private = address.is_private or address.is_loopback
        except ValueError:
            pass
        if not is_private:
            raise ProviderError(
                code="PROVIDER_URL_UNSAFE",
                provider="custom",
                message="Public custom provider URLs must use HTTPS",
            )
