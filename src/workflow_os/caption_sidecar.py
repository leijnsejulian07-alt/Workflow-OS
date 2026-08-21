from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .caption_segments import CaptionSegment

_MAX_SEGMENTS = 20_000
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CaptionSidecar:
    relative_path: str
    size_bytes: int
    sha256: str
    segment_count: int


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _relative_srt_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("output_relative_path must be a string")
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        raise ValueError("output_relative_path must be 1..500 characters")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("output_relative_path must be relative and traversal-free")
    if path.suffix.lower() != ".srt":
        raise ValueError("output_relative_path must end in .srt")
    return path


def _format_srt_time(milliseconds: int) -> str:
    milliseconds = _bounded_int(milliseconds, "milliseconds", 0, 24 * 60 * 60 * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt_text(segments: Iterable[CaptionSegment]) -> str:
    materialized = list(segments)
    if not 1 <= len(materialized) <= _MAX_SEGMENTS:
        raise ValueError(f"segments must contain 1..{_MAX_SEGMENTS} values")

    blocks: list[str] = []
    previous_end = -1
    for number, segment in enumerate(materialized, start=1):
        if not isinstance(segment, CaptionSegment):
            raise ValueError("segments must contain CaptionSegment values")
        start_ms = _bounded_int(segment.start_ms, "start_ms", 0, 24 * 60 * 60 * 1000)
        end_ms = _bounded_int(segment.end_ms, "end_ms", 1, 24 * 60 * 60 * 1000)
        if end_ms <= start_ms:
            raise ValueError("caption end_ms must be greater than start_ms")
        if start_ms < previous_end:
            raise ValueError("caption segments must be monotonic and non-overlapping")
        if not isinstance(segment.text, str):
            raise ValueError("caption text must be a string")
        text = " ".join(segment.text.split())
        if not text or len(text) > 1_000:
            raise ValueError("caption text must contain 1..1000 normalized characters")
        if any(ord(char) < 32 for char in segment.text):
            raise ValueError("caption text contains control characters")
        blocks.append(
            f"{number}\n{_format_srt_time(start_ms)} --> {_format_srt_time(end_ms)}\n{text}\n"
        )
        previous_end = end_ms

    return "\n".join(blocks)


def write_caption_sidecar(
    workspace_root: str | os.PathLike[str],
    output_relative_path: str,
    segments: Iterable[CaptionSegment],
    *,
    max_output_bytes: int = _MAX_OUTPUT_BYTES,
) -> CaptionSidecar:
    """Write a bounded UTF-8 SRT sidecar without shelling out or overwriting files."""

    max_output_bytes = _bounded_int(max_output_bytes, "max_output_bytes", 1, _MAX_OUTPUT_BYTES)
    relative = _relative_srt_path(output_relative_path)
    text = render_srt_text(segments)
    payload = text.encode("utf-8")
    if not 1 <= len(payload) <= max_output_bytes:
        raise ValueError("caption sidecar size is outside allowed bounds")

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")
    output_path = root.joinpath(*relative.parts)
    parent = output_path.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("output path escapes workspace_root") from exc
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("output path already exists")

    temp_path = parent / f".{output_path.stem}.{uuid.uuid4().hex}.tmp.srt"
    try:
        with temp_path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temp_path.is_symlink() or temp_path.stat().st_size != len(payload):
            raise RuntimeError("caption sidecar write verification failed")
        os.replace(temp_path, output_path)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

    return CaptionSidecar(
        relative_path=relative.as_posix(),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        segment_count=text.count(" --> "),
    )
