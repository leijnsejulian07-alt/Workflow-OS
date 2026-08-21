from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..production_handoff import ProducerOutput
from .local_media_ingest import ingest_local_media

_MAX_START_MS = 24 * 60 * 60 * 1000
_MAX_DURATION_MS = 3 * 60 * 1000
_MAX_OUTPUT_BYTES = 512 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 10 * 60


@dataclass(frozen=True)
class ClipRenderSpec:
    source: ProducerOutput
    output_relative_path: str
    start_ms: int
    duration_ms: int


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _relative_mp4_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("output_relative_path must be a string")
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        raise ValueError("output_relative_path must be 1..500 characters")
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("output_relative_path must be relative and traversal-free")
    if path.suffix.lower() != ".mp4":
        raise ValueError("output_relative_path must end in .mp4")
    return path


def _verify_source(workspace_root: Path, source: ProducerOutput) -> ProducerOutput:
    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")
    current = ingest_local_media(
        workspace_root,
        source.relative_path,
        producer=source.producer,
        max_bytes=source.size_bytes,
    )
    if current.media_type not in {"video/mp4", "video/webm"}:
        raise ValueError("source must be a supported video")
    if current.size_bytes != source.size_bytes or current.sha256 != source.sha256:
        raise ValueError("source media no longer matches producer evidence")
    return current


def build_ffmpeg_clip_command(
    ffmpeg_executable: str,
    source_path: Path,
    output_path: Path,
    *,
    start_ms: int,
    duration_ms: int,
) -> tuple[str, ...]:
    if not isinstance(ffmpeg_executable, str) or not ffmpeg_executable.strip():
        raise ValueError("ffmpeg_executable must be a non-empty string")
    start_ms = _bounded_int(start_ms, "start_ms", 0, _MAX_START_MS)
    duration_ms = _bounded_int(duration_ms, "duration_ms", 250, _MAX_DURATION_MS)

    return (
        ffmpeg_executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-t",
        f"{duration_ms / 1000:.3f}",
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


def render_clip(
    workspace_root: str | os.PathLike[str],
    spec: ClipRenderSpec,
    *,
    producer: str = "ffmpeg-clip-v1",
    max_output_bytes: int = _MAX_OUTPUT_BYTES,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ffmpeg_executable: str = "ffmpeg",
) -> ProducerOutput:
    """Render one bounded clip with direct FFmpeg arguments and no shell.

    Source evidence is re-verified immediately before rendering. Output is first
    written to a unique temporary MP4 in the requested directory, then validated
    and atomically promoted. Rights, campaign compliance, disclosure and QC are
    deliberately outside this adapter and must still come from trusted Workflow
    OS evidence before publication.
    """

    if not isinstance(spec, ClipRenderSpec):
        raise ValueError("spec must be ClipRenderSpec")
    max_output_bytes = _bounded_int(max_output_bytes, "max_output_bytes", 1, _MAX_OUTPUT_BYTES)
    timeout_seconds = _bounded_int(timeout_seconds, "timeout_seconds", 1, 60 * 60)
    output_relative = _relative_mp4_path(spec.output_relative_path)

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")

    source = _verify_source(root, spec.source)
    source_path = root.joinpath(*PurePosixPath(source.relative_path).parts).resolve(strict=True)

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
    command = build_ffmpeg_clip_command(
        resolved_ffmpeg,
        source_path,
        temp_path,
        start_ms=spec.start_ms,
        duration_ms=spec.duration_ms,
    )

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
            raise RuntimeError("ffmpeg render failed")
        if not temp_path.exists() or temp_path.is_symlink():
            raise RuntimeError("ffmpeg did not produce a regular output file")
        stat_result = temp_path.stat()
        if not 1 <= stat_result.st_size <= max_output_bytes:
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
