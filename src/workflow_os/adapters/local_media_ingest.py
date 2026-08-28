from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..production_handoff import ProducerOutput

_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024
_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("relative_path must be a string")
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        raise ValueError("relative_path must be 1..500 characters")
    path = PurePosixPath(cleaned)
    windows_path = PureWindowsPath(value.strip())
    if path.is_absolute() or windows_path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("relative_path must be relative and traversal-free")
    return path


def _producer(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("producer must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 200:
        raise ValueError("producer must be 1..200 characters")
    return cleaned


def ingest_local_media(
    workspace_root: str | os.PathLike[str],
    relative_path: str,
    *,
    producer: str = "local-media-ingest-v1",
    max_bytes: int = _MAX_ASSET_BYTES,
) -> ProducerOutput:
    """Convert one existing local media file into hostile producer metadata.

    This adapter deliberately proves only bounded local file facts. It does not
    infer rights, campaign compliance, disclosure, or QC; those facts must still
    come from Workflow OS-owned ``TrustedProductionEvidence`` before publication.
    """

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    max_bytes = min(max_bytes, _MAX_ASSET_BYTES)

    relative = _relative_path(relative_path)
    producer_name = _producer(producer)

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")

    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise ValueError("symlink media inputs are not allowed")

    resolved = candidate.resolve(strict=True)
    try:
        normalized_relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("media input escapes workspace_root") from exc

    suffix = resolved.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise ValueError("media type is not allowed")

    digest = hashlib.sha256()
    bytes_read = 0
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("media input must be a regular file")
        if not 1 <= before.st_size <= max_bytes:
            raise ValueError("media input size is outside allowed bounds")

        while True:
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise ValueError("media input exceeded allowed bounds while reading")
            digest.update(chunk)

        after = os.fstat(handle.fileno())

    if bytes_read != before.st_size:
        raise ValueError("media input changed while reading")
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError("media input changed while reading")

    return ProducerOutput(
        relative_path=normalized_relative,
        media_type=media_type,
        size_bytes=bytes_read,
        sha256=digest.hexdigest(),
        producer=producer_name,
    )
