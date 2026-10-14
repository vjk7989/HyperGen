from __future__ import annotations

from typing import TypeVar

from api_types import IcLoraCatalogItem, LoraCatalogItem, MediaSpec

_T = TypeVar("_T", LoraCatalogItem, IcLoraCatalogItem)


def resolve_media_url(path: str | None) -> str | None:
    """Keep explicit HTTPS media URLs and omit retired relative catalog previews."""
    if path is None or path == "":
        return path
    if path.startswith("https://"):
        return path
    return None


def with_resolved_media(item: _T) -> _T:
    """Return a copy with safe explicit media URLs and no retired CDN paths."""
    media = item.media
    if media is None:
        return item
    thumbnail = resolve_media_url(media.thumbnail)
    demo_video = resolve_media_url(media.demo_video)
    if thumbnail == media.thumbnail and demo_video == media.demo_video:
        return item
    return item.model_copy(update={"media": MediaSpec(thumbnail=thumbnail, demo_video=demo_video)})
