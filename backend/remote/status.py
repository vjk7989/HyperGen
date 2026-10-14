"""Status payload advertised to Desktop Settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from state.app_settings import RemoteExposure

TunnelState = Literal["off", "starting", "ready", "error"]


class RemoteStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permitted: bool
    serving: bool
    url: str | None = None
    localUrl: str | None = None
    lanUrl: str | None = None
    publicUrl: str | None = None
    tunnelState: TunnelState = "off"
    reason: str | None = None
    mode: RemoteExposure | None = None
