from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .adapters.ffmpeg_caption_burn import CaptionBurnSpec, burn_captions
from .adapters.ffmpeg_clip import render_clip
from .caption_segments import TranscriptWord, plan_caption_segments
from .caption_sidecar import write_caption_sidecar
from .clip_selection import SelectedClip
from .production_handoff import ProducerOutput


@dataclass(frozen=True)
class CaptionedClipResult:
    candidate_id: str
    ranking_score: float
    analysis_evidence_sha256: str
    caption_segment_count: int
    output: ProducerOutput


def _relative_path(value: object, *, suffix: str, field: str) -> PurePosixPath:
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


def _safe_unlink(root: Path, relative: PurePosixPath) -> None:
    candidate = root.joinpath(*relative.parts)
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (FileNotFoundError, ValueError, OSError):
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        pass


def produce_captioned_clip(
    workspace_root: str | os.PathLike[str],
    selected: SelectedClip,
    transcript_words: Iterable[TranscriptWord],
    *,
    caption_relative_path: str,
    output_relative_path: str,
    cleanup_intermediates: bool = True,
    ffmpeg_executable: str = "ffmpeg",
    timeout_seconds: int = 10 * 60,
) -> CaptionedClipResult:
    """Execute one bounded clip -> captions -> caption-burn production attempt.

    All validation that can be performed without side effects happens before the
    first render. Intermediate clip/SRT files are removed automatically after
    success and on bounded failure where safe. The returned ProducerOutput remains
    untrusted: rights, campaign compliance, disclosure, QC and publication
    authority must still be supplied by downstream Workflow OS-owned evidence.
    """

    if not isinstance(selected, SelectedClip):
        raise ValueError("selected must be SelectedClip")
    if cleanup_intermediates is not True and cleanup_intermediates is not False:
        raise ValueError("cleanup_intermediates must be a boolean")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise ValueError("timeout_seconds must be an integer")
    if not 1 <= timeout_seconds <= 60 * 60:
        raise ValueError("timeout_seconds must be between 1 and 3600")
    if not isinstance(ffmpeg_executable, str) or not ffmpeg_executable.strip():
        raise ValueError("ffmpeg_executable must be a non-empty string")

    clip_relative = _relative_path(
        selected.render_spec.output_relative_path,
        suffix=".mp4",
        field="clip output_relative_path",
    )
    caption_relative = _relative_path(
        caption_relative_path,
        suffix=".srt",
        field="caption_relative_path",
    )
    final_relative = _relative_path(
        output_relative_path,
        suffix=".mp4",
        field="output_relative_path",
    )
    if clip_relative == final_relative:
        raise ValueError("intermediate clip and final output paths must differ")

    # Materialize and validate transcript/caption planning before any file write.
    words = list(transcript_words)
    segments = plan_caption_segments(
        words,
        clip_start_ms=selected.render_spec.start_ms,
        clip_duration_ms=selected.render_spec.duration_ms,
    )

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace_root must be a directory")

    clip_created = False
    caption_created = False
    completed = False
    try:
        clip_output = render_clip(
            root,
            selected.render_spec,
            timeout_seconds=timeout_seconds,
            ffmpeg_executable=ffmpeg_executable,
        )
        clip_created = True
        sidecar = write_caption_sidecar(root, caption_relative.as_posix(), segments)
        caption_created = True
        final_output = burn_captions(
            root,
            CaptionBurnSpec(
                source=clip_output,
                captions=sidecar,
                output_relative_path=final_relative.as_posix(),
            ),
            timeout_seconds=timeout_seconds,
            ffmpeg_executable=ffmpeg_executable,
        )
        completed = True
        return CaptionedClipResult(
            candidate_id=selected.candidate_id,
            ranking_score=selected.ranking_score,
            analysis_evidence_sha256=selected.analysis_evidence_sha256,
            caption_segment_count=len(segments),
            output=final_output,
        )
    finally:
        if cleanup_intermediates or not completed:
            if caption_created:
                _safe_unlink(root, caption_relative)
            if clip_created:
                _safe_unlink(root, clip_relative)
