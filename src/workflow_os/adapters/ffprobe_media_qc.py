from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..production_handoff import ProducerOutput
from .local_media_ingest import ingest_local_media

_MAX_TIMEOUT_SECONDS = 60
_MAX_PROBE_OUTPUT_BYTES = 64 * 1024
_MIN_DIMENSION = 240
_MAX_DIMENSION = 4320
_MAX_PIXELS = 12_000_000


@dataclass(frozen=True)
class MediaQCResult:
    passed: bool
    reason: str
    duration_ms: int | None
    width: int | None
    height: int | None
    video_codec: str | None
    has_audio: bool


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _verify_source(workspace_root: Path, source: ProducerOutput) -> tuple[ProducerOutput, Path]:
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
    relative = PurePosixPath(current.relative_path.replace("\\", "/"))
    path = workspace_root.joinpath(*relative.parts).resolve(strict=True)
    try:
        path.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("source path escapes workspace_root") from exc
    return current, path


def _parse_duration_ms(value: object) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0 or seconds > 24 * 60 * 60:
        return None
    return int(round(seconds * 1000))


def _parse_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def probe_media_qc(
    workspace_root: str | os.PathLike[str],
    source: ProducerOutput,
    *,
    expected_duration_ms: int | None = None,
    duration_tolerance_ms: int = 1500,
    require_audio: bool = False,
    timeout_seconds: int = 20,
    ffprobe_executable: str = "ffprobe",
) -> MediaQCResult:
    """Verify rendered media with bounded ffprobe output and fail-closed rules.

    This adapter grants no rights, campaign compliance, disclosure or publication
    authority. It only supplies deterministic technical QC evidence for a local
    produced video before Workflow OS may mark trusted production evidence as QC-passed.
    """

    if expected_duration_ms is not None:
        expected_duration_ms = _bounded_int(expected_duration_ms, "expected_duration_ms", 250, 3 * 60 * 1000)
    duration_tolerance_ms = _bounded_int(duration_tolerance_ms, "duration_tolerance_ms", 0, 10_000)
    timeout_seconds = _bounded_int(timeout_seconds, "timeout_seconds", 1, _MAX_TIMEOUT_SECONDS)
    if require_audio is not True and require_audio is not False:
        raise ValueError("require_audio must be a boolean")
    if not isinstance(ffprobe_executable, str) or not ffprobe_executable.strip():
        raise ValueError("ffprobe_executable must be a non-empty string")

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")
    _, source_path = _verify_source(root, source)

    resolved_ffprobe = shutil.which(ffprobe_executable)
    if resolved_ffprobe is None:
        raise RuntimeError("ffprobe executable is not available")

    command = (
        resolved_ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,duration",
        "-of",
        "json",
        str(source_path),
    )
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        timeout=timeout_seconds,
        check=False,
        cwd=root,
    )
    if completed.returncode != 0:
        return MediaQCResult(False, "ffprobe failed", None, None, None, None, False)
    if not isinstance(completed.stdout, (bytes, bytearray)) or len(completed.stdout) > _MAX_PROBE_OUTPUT_BYTES:
        return MediaQCResult(False, "ffprobe output is outside allowed bounds", None, None, None, None, False)

    try:
        payload = json.loads(bytes(completed.stdout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return MediaQCResult(False, "ffprobe returned malformed JSON", None, None, None, None, False)
    if not isinstance(payload, dict):
        return MediaQCResult(False, "ffprobe returned malformed payload", None, None, None, None, False)

    streams = payload.get("streams")
    if not isinstance(streams, list) or len(streams) > 32:
        return MediaQCResult(False, "stream metadata is invalid", None, None, None, None, False)
    video_streams = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if len(video_streams) != 1:
        return MediaQCResult(False, "exactly one video stream is required", None, None, None, None, bool(audio_streams))

    video = video_streams[0]
    width = _parse_positive_int(video.get("width"))
    height = _parse_positive_int(video.get("height"))
    codec = video.get("codec_name") if isinstance(video.get("codec_name"), str) else None
    if width is None or height is None:
        return MediaQCResult(False, "video dimensions are missing", None, width, height, codec, bool(audio_streams))
    if not (_MIN_DIMENSION <= width <= _MAX_DIMENSION and _MIN_DIMENSION <= height <= _MAX_DIMENSION):
        return MediaQCResult(False, "video dimensions are outside allowed bounds", None, width, height, codec, bool(audio_streams))
    if width * height > _MAX_PIXELS:
        return MediaQCResult(False, "video pixel count is outside allowed bounds", None, width, height, codec, bool(audio_streams))
    if codec not in {"h264", "hevc", "vp9", "av1"}:
        return MediaQCResult(False, "video codec is not allowed", None, width, height, codec, bool(audio_streams))

    format_meta = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration_ms = _parse_duration_ms(format_meta.get("duration")) or _parse_duration_ms(video.get("duration"))
    if duration_ms is None:
        return MediaQCResult(False, "video duration is missing or invalid", None, width, height, codec, bool(audio_streams))
    if expected_duration_ms is not None and abs(duration_ms - expected_duration_ms) > duration_tolerance_ms:
        return MediaQCResult(False, "video duration does not match the expected clip", duration_ms, width, height, codec, bool(audio_streams))
    if require_audio and not audio_streams:
        return MediaQCResult(False, "audio stream is required", duration_ms, width, height, codec, False)

    return MediaQCResult(True, "technical media QC passed", duration_ms, width, height, codec, bool(audio_streams))
