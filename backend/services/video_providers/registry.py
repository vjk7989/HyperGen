from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from services.video_providers.errors import ProviderError
from services.video_providers.models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderTextToVideoRequest,
)


@runtime_checkable
class TextToVideoProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def generate(
        self,
        request: ProviderTextToVideoRequest,
        profile: ProviderProfile,
        output_path: Path,
        *,
        on_progress: Callable[[int], None],
        is_cancelled: Callable[[], bool],
    ) -> None: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TextToVideoProvider] = {}

    def register(self, provider: TextToVideoProvider) -> None:
        provider_id = provider.provider_id
        if provider_id in self._providers:
            raise ProviderError(
                code="PROVIDER_ALREADY_REGISTERED",
                provider=provider_id,
                message=f"Video provider already registered: {provider_id}",
            )
        self._providers[provider_id] = provider

    def resolve(self, provider_id: str) -> TextToVideoProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderError(
                code="PROVIDER_NOT_FOUND",
                provider=provider_id,
                message=f"Unknown video provider: {provider_id}",
            ) from exc
