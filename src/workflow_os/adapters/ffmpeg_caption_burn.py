from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..caption_sidecar import CaptionSidecar
from ..production_handoff import ProducerOutput
from .local_media_ingest import ingest_local_media

_MAX_OUTPUT_BYTES = 512 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 10 * 60


@dataclass(frozen=True)
class CaptionBurnSpec:
    source: ProducerOutput
    captions: CaptionSidecar
    output_relative_path: str


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _relative_path(value: object, suffix: str, field: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        raise ValueError(f"{field} must be 1..500 characters")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"{field} must be relative and traversal-free")
    if path.suffix.lower() != suffix:
        raise ValueError(f"{field} must end in {suffix}")
    return path


def _resolve_existing(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("input path escapes workspace_root") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise ValueError("input must be a regular non-symlink file")
    return resolved


def _verify_caption_sidecar(root: Path, sidecar: CaptionSidecar) -> Path:
    if not isinstance(sidecar, CaptionSidecar):
        raise ValueError("captions must be CaptionSidecar")
    relative = _relative_path(sidecar.relative_path, ".srt", "caption relative_path")
    path = _resolve_existing(root, relative)
    payload = path.read_bytes()
    if len(payload) != sidecar.size_bytes:
        raise ValueError("caption sidecar size no longer matches evidence")
    if hashlib.sha256(payload).hexdigest() != sidecar.sha256:
        raise ValueError("caption sidecar digest no longer matches evidence")
    return path


def _escape_subtitle_path(path: Path) -> str:
    value = path.as_posix().replace("\\", "/")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    return value


def build_ffmpeg_caption_command(
    ffmpeg_executable: str,
    source_path: Path,
    caption_path: Path,
    output_path: Path,
) -> tuple[str, ...]:
    if not isinstance(ffmpeg_executable, str) or not ffmpeg_executable.strip():
        raise ValueError("ffmpeg_executable must be a non-empty string")
    caption_filter = "subtitles=filename='" + _escape_subtitle_path(caption_path) + "'"
    return (
        ffmpeg_executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-vf",
        caption_filter,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(output_path),
    )


def burn_captions(
    workspace_root: str | os.PathLike[str],
    spec: CaptionBurnSpec,
    *,
    producer: str = "ffmpeg-caption-burn-v1",
    max_output_bytes: int = _MAX_OUTPUT_BYTES,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ffmpeg_executable: str = "ffmpeg",
) -> ProducerOutput:
    """Burn a verified SRT into a verified local video with bounded FFmpeg execution."""

    if not isinstance(spec, CaptionBurnSpec):
        raise ValueError("spec must be CaptionBurnSpec")
    max_output_bytes = _bounded_int(max_output_bytes, "max_output_bytes", 1, _MAX_OUTPUT_BYTES)
    timeout_seconds = _bounded_int(timeout_seconds, "timeout_seconds", 1, 60 * 60)
    output_relative = _relative_path(spec.output_relative_path, ".mp4", "output_relative_path")

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")

    source = ingest_local_media(
        root,
        spec.source.relative_path,
        producer=spec.source.producer,
        max_bytes=spec.source.size_bytes,
    )
    if source.size_bytes != spec.source.size_bytes or source.sha256 != spec.source.sha256:
        raise ValueError("source media no longer matches producer evidence")
    if source.media_type not in {"video/mp4", "video/webm"}:
        raise ValueError("source must be a supported video")
    source_path = _resolve_existing(root, PurePosixPath(source.relative_path))
    caption_path = _verify_caption_sidecar(root, spec.captions)

    output_path = root.joinpath(*output_relative.parts)
    parent = output_path.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("output path escapes workspace_root") from exc
    if output_path.exists() or output_path.is_symlink():
        raise ValueError("output path already exists")

    resolved_ffmpeg = shutil.which(ffmpeg_executable)
    if resolved_ffmpeg is None:
        raise RuntimeError("ffmpeg executable is not available")

    temp_path = parent / f".{output_path.stem}.{uuid.uuid4().hex}.tmp.mp4"
    command = build_ffmpeg_caption_command(resolved_ffmpeg, source_path, caption_path, temp_path)
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=timeout_seconds,
            check=False,
            cwd=root,
        )
        if completed.returncode != 0:
            raise RuntimeError("ffmpeg caption render failed")
        if not temp_path.exists() or temp_path.is_symlink():
            raise RuntimeError("ffmpeg did not produce a regular output file")
        size = temp_path.stat().st_size
        if not 1 <= size <= max_output_bytes:
            raise RuntimeError("ffmpeg output size is outside allowed bounds")
        os.replace(temp_path, output_path)
        return ingest_local_media(
            root,
            output_relative.as_posix(),
            producer=producer,
            max_bytes=max_output_bytes,
        )
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
