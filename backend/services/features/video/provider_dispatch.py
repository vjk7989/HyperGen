from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from api_types import TextToVideoParams, TextToVideoProviderTarget
from services.features.video.text_to_video import (
    TextToVideoExecutor,
    VIDEO_OUTPUT_PLAN,
    require_video_output,
)
from services.generation_interrupt import (
    GenerationCancelledError,
    is_cancel_exception,
    is_requested,
)
from services.generation_queue.types import OutputAllocation, OutputPlan
from services.records import CapabilityFailedError, GenerationRecord
from services.video_providers import (
    ProviderError,
    ProviderRegistry,
    ProviderTextToVideoRequest,
)
from services.video_providers.persistence import ProviderProfileStore


class ProviderGenerationLifecycle(Protocol):
    def start_api_generation(self, generation_id: str) -> None: ...

    def complete_generation(self, result: str | list[str] | None = None) -> None: ...

    def fail_generation(self, error: str) -> None: ...


def _discard_progress(_progress: int) -> None:
    return None


class ProviderDispatchTextToVideoExecutor:
    """Dispatch plain T2V v2 jobs while preserving the local v1 executor."""

    def __init__(
        self,
        *,
        local_executor: TextToVideoExecutor,
        providers: ProviderRegistry,
        profiles: ProviderProfileStore,
        progress_sink: Callable[[int], None] | None = None,
        lifecycle: ProviderGenerationLifecycle | None = None,
    ) -> None:
        self._local = local_executor
        self._providers = providers
        self._profiles = profiles
        self._progress_sink: Callable[[int], None] = progress_sink or _discard_progress
        self._lifecycle = lifecycle

    def validate_params(
        self, spec: Mapping[str, object], *, contract_version: int
    ) -> None:
        if contract_version == 1:
            self._local.validate_params(spec, contract_version=contract_version)
            return
        if contract_version != 2:
            raise ValueError(f"Unsupported generation contract version: {contract_version}")
        self._params(spec)
        self._target(spec)

    def plan_outputs(self, generation: GenerationRecord) -> tuple[OutputPlan, ...]:
        if generation.contract_version == 1:
            return self._local.plan_outputs(generation)
        self.validate_params(generation.spec, contract_version=generation.contract_version)
        return (VIDEO_OUTPUT_PLAN,)

    def execute(
        self,
        generation: GenerationRecord,
        outputs: tuple[OutputAllocation, ...],
    ) -> None:
        if generation.contract_version == 1:
            self._local.execute(generation, outputs)
            return

        output = require_video_output(outputs)
        try:
            params = self._params(generation.spec)
            target = self._target(generation.spec)
            profile = self._profiles.get_profile(target.providerId)
            if profile is None:
                raise ProviderError(
                    code="PROVIDER_CONFIGURATION_INVALID",
                    provider=target.providerId,
                    message=f"Video provider is not configured: {target.providerId}",
                )
            provider = self._providers.resolve(target.providerId)
            if not provider.capabilities.text_to_video:
                raise ProviderError(
                    code="PROVIDER_CAPABILITY_UNSUPPORTED",
                    provider=target.providerId,
                    message="Provider does not support text-to-video generation",
                )
            request = ProviderTextToVideoRequest(
                prompt=params.prompt,
                model_id=target.modelId,
                aspect_ratio=params.aspectRatio,
                resolution=params.resolution,
                duration=params.duration,
                fps=params.fps,
                generate_audio=params.audio,
                negative_prompt=params.negativePrompt,
                seed=params.seed,
            )
            if self._lifecycle is not None:
                self._lifecycle.start_api_generation(generation.id)
            provider.generate(
                request,
                profile,
                Path(output.dest_path),
                on_progress=self._progress_sink,
                is_cancelled=is_requested,
            )
            if self._lifecycle is not None:
                self._lifecycle.complete_generation(output.dest_path)
        except Exception as exc:
            if is_cancel_exception(exc):
                raise GenerationCancelledError() from exc
            if self._lifecycle is not None:
                self._lifecycle.fail_generation("Provider generation failed")
            if isinstance(exc, ProviderError):
                raise CapabilityFailedError(exc.message) from exc
            raise

    @staticmethod
    def _params(spec: Mapping[str, object]) -> TextToVideoParams:
        params = spec.get("params")
        if not isinstance(params, Mapping):
            raise ValueError("generation spec requires a params object")
        return TextToVideoParams.model_validate(params)

    @staticmethod
    def _target(spec: Mapping[str, object]) -> TextToVideoProviderTarget:
        target = spec.get("provider")
        if not isinstance(target, Mapping):
            raise ValueError("provider generation requires a provider target")
        return TextToVideoProviderTarget.model_validate(target)
