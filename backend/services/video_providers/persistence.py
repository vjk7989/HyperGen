from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from services.video_providers.models import PROVIDER_IDS, ProviderProfile

logger = logging.getLogger(__name__)


class _StoredProfiles(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    active_provider: str = "local"
    profiles: dict[str, ProviderProfile] = Field(default_factory=dict)


class ProviderProfileStore:
    """Atomic, plaintext provider profile storage with redaction at its boundary."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._state = self._read()

    @property
    def active_provider(self) -> str:
        with self._lock:
            return self._state.active_provider

    def get_profile(self, provider_id: str) -> ProviderProfile | None:
        with self._lock:
            return self._state.profiles.get(provider_id)

    def list_profiles(self) -> tuple[ProviderProfile, ...]:
        with self._lock:
            profiles = self._state.profiles
            return tuple(profiles[provider_id] for provider_id in PROVIDER_IDS if provider_id in profiles)

    def save_profile(self, profile: ProviderProfile) -> ProviderProfile:
        with self._lock:
            profiles = dict(self._state.profiles)
            profiles[profile.provider_id] = profile
            proposed = self._state.model_copy(update={"profiles": profiles}, deep=True)
            self._write(proposed)
            self._state = proposed
            return profile

    def set_active_provider(self, provider_id: str) -> str:
        with self._lock:
            proposed = self._state.model_copy(
                update={"active_provider": provider_id}, deep=True
            )
            self._write(proposed)
            self._state = proposed
            return provider_id

    def _read(self) -> _StoredProfiles:
        try:
            return _StoredProfiles.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return _StoredProfiles()
        except (OSError, ValueError) as exc:
            logger.warning("Could not read %s, using provider defaults: %s", self._path, exc)
            return _StoredProfiles()

    def _write(self, state: _StoredProfiles) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".json.tmp")
        payload = state.model_dump(mode="json", by_alias=False)
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._path)
