from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app_handler import AppHandler
from handlers.video_provider_handler import (
    ActiveProviderResponse,
    ActiveProviderUpdate,
    ProviderProfileUpdate,
    ProviderValidationResponse,
    VideoProviderSnapshot,
)
from services.video_providers import ProviderError, PublicProviderProfile
from state import get_state_service
from state.app_settings import UpdateSettingsRequest

router = APIRouter(prefix="/api/video-providers", tags=["video-providers"])


def _error_response(error: ProviderError) -> JSONResponse:
    status_code = 404 if error.code == "PROVIDER_NOT_FOUND" else 400
    return JSONResponse(status_code=status_code, content=error.to_dict())


@router.get("", response_model=VideoProviderSnapshot)
def route_get_video_providers(
    handler: AppHandler = Depends(get_state_service),
) -> VideoProviderSnapshot:
    return handler.video_providers.get_snapshot()


@router.put("/active", response_model=ActiveProviderResponse)
def route_set_active_video_provider(
    req: ActiveProviderUpdate,
    handler: AppHandler = Depends(get_state_service),
) -> ActiveProviderResponse | JSONResponse:
    try:
        return handler.video_providers.set_active_provider(req.provider_id)
    except ProviderError as error:
        return _error_response(error)


@router.post("/{provider_id}/validate", response_model=ProviderValidationResponse)
def route_validate_video_provider(
    provider_id: str,
    req: ProviderProfileUpdate | None = None,
    handler: AppHandler = Depends(get_state_service),
) -> ProviderValidationResponse | JSONResponse:
    try:
        return handler.video_providers.validate(provider_id, req)
    except ProviderError as error:
        return _error_response(error)


@router.put("/{provider_id}", response_model=PublicProviderProfile)
def route_update_video_provider(
    provider_id: str,
    req: ProviderProfileUpdate,
    handler: AppHandler = Depends(get_state_service),
) -> PublicProviderProfile | JSONResponse:
    try:
        profile = handler.video_providers.update_profile(provider_id, req)
        if provider_id == "ltx" and "api_key" in req.model_fields_set:
            handler.settings.update_settings(
                UpdateSettingsRequest.model_validate({"ltx_api_key": req.api_key})
            )
        return profile
    except ProviderError as error:
        return _error_response(error)
