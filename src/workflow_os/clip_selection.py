from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Iterable

from .adapters.ffmpeg_clip import ClipRenderSpec
from .production_handoff import ProducerOutput

_MAX_CANDIDATES = 100
_MAX_START_MS = 24 * 60 * 60 * 1000
_MAX_DURATION_MS = 3 * 60 * 1000


@dataclass(frozen=True)
class ClipCandidate:
    candidate_id: str
    start_ms: int
    duration_ms: int
    hook_score: float
    relevance_score: float
    quality_score: float
    analysis_evidence_sha256: str


@dataclass(frozen=True)
class SelectedClip:
    candidate_id: str
    render_spec: ClipRenderSpec
    ranking_score: float
    analysis_evidence_sha256: str


def _bounded_text(value: object, field: str, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} must be 1..{maximum} characters")
    return cleaned


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _unit_score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{field} must be finite and between 0 and 1")
    return score


def _sha256(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("analysis_evidence_sha256 must be a string")
    cleaned = value.strip().lower()
    if len(cleaned) != 64:
        raise ValueError("analysis_evidence_sha256 must be a SHA-256 digest")
    try:
        bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError("analysis_evidence_sha256 must be a SHA-256 digest") from exc
    return cleaned


def _validate_candidate(candidate: ClipCandidate) -> ClipCandidate:
    if not isinstance(candidate, ClipCandidate):
        raise ValueError("candidates must contain ClipCandidate values")
    return ClipCandidate(
        candidate_id=_bounded_text(candidate.candidate_id, "candidate_id"),
        start_ms=_bounded_int(candidate.start_ms, "start_ms", 0, _MAX_START_MS),
        duration_ms=_bounded_int(candidate.duration_ms, "duration_ms", 250, _MAX_DURATION_MS),
        hook_score=_unit_score(candidate.hook_score, "hook_score"),
        relevance_score=_unit_score(candidate.relevance_score, "relevance_score"),
        quality_score=_unit_score(candidate.quality_score, "quality_score"),
        analysis_evidence_sha256=_sha256(candidate.analysis_evidence_sha256),
    )


def _ranking_score(candidate: ClipCandidate) -> float:
    # Keep the policy intentionally simple and inspectable. External AI may propose
    # candidates and scores, but it receives no rights/publication authority here.
    return (
        candidate.hook_score * 0.45
        + candidate.relevance_score * 0.35
        + candidate.quality_score * 0.20
    )


def select_clip_candidate(
    source: ProducerOutput,
    candidates: Iterable[ClipCandidate],
    *,
    output_relative_path: str,
) -> SelectedClip:
    """Select one bounded clip proposal for rendering.

    This boundary treats external clip-analysis output as untrusted timing/ranking
    advice only. It cannot establish rights, campaign compliance, disclosure, QC,
    account authorization or publication eligibility. Those remain downstream
    Workflow OS-owned gates.
    """

    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")
    if not isinstance(output_relative_path, str) or not output_relative_path.strip():
        raise ValueError("output_relative_path must be a non-empty string")

    materialized = list(candidates)
    if not 1 <= len(materialized) <= _MAX_CANDIDATES:
        raise ValueError(f"candidates must contain 1..{_MAX_CANDIDATES} values")

    validated = [_validate_candidate(candidate) for candidate in materialized]
    ids = [candidate.candidate_id for candidate in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate_id values must be unique")

    best = max(
        validated,
        key=lambda candidate: (
            _ranking_score(candidate),
            candidate.hook_score,
            candidate.relevance_score,
            candidate.quality_score,
            -candidate.start_ms,
            candidate.candidate_id,
        ),
    )
    score = _ranking_score(best)
    return SelectedClip(
        candidate_id=best.candidate_id,
        render_spec=ClipRenderSpec(
            source=source,
            output_relative_path=output_relative_path,
            start_ms=best.start_ms,
            duration_ms=best.duration_ms,
        ),
        ranking_score=score,
        analysis_evidence_sha256=best.analysis_evidence_sha256,
    )


def evidence_digest_for_analysis(payload: bytes) -> str:
    """Return a stable digest callers can bind to persisted analysis evidence."""

    if not isinstance(payload, bytes):
        raise ValueError("payload must be bytes")
    if not payload:
        raise ValueError("payload must not be empty")
    return hashlib.sha256(payload).hexdigest()
