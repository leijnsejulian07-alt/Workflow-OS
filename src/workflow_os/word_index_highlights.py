from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .clip_selection import ClipCandidate, evidence_digest_for_analysis

_MAX_WORDS = 200_000
_MAX_PROPOSALS = 100
_MAX_TIMESTAMP_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class WordTiming:
    word_index: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class WordSpanProposal:
    candidate_id: str
    start_word_index: int
    end_word_index: int
    hook_score: float
    relevance_score: float
    quality_score: float


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _candidate_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("candidate_id must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 160:
        raise ValueError("candidate_id must be 1..160 characters")
    return cleaned


def _unit_score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{field} must be finite and between 0 and 1")
    return score


def _validate_words(words: Iterable[WordTiming]) -> dict[int, WordTiming]:
    materialized = list(words)
    if not 1 <= len(materialized) <= _MAX_WORDS:
        raise ValueError(f"words must contain 1..{_MAX_WORDS} values")

    by_index: dict[int, WordTiming] = {}
    previous_end = -1
    for expected_index, word in enumerate(materialized):
        if not isinstance(word, WordTiming):
            raise ValueError("words must contain WordTiming values")
        index = _bounded_int(word.word_index, "word_index", 0, _MAX_WORDS - 1)
        start_ms = _bounded_int(word.start_ms, "start_ms", 0, _MAX_TIMESTAMP_MS)
        end_ms = _bounded_int(word.end_ms, "end_ms", 1, _MAX_TIMESTAMP_MS)
        if index != expected_index:
            raise ValueError("word_index values must be contiguous and zero-based")
        if end_ms <= start_ms:
            raise ValueError("word timing end_ms must be greater than start_ms")
        if start_ms < previous_end:
            raise ValueError("word timings must be monotonic and non-overlapping")
        previous_end = end_ms
        by_index[index] = WordTiming(index, start_ms, end_ms)
    return by_index


def candidates_from_word_spans(
    words: Iterable[WordTiming],
    proposals: Iterable[WordSpanProposal],
    *,
    analysis_evidence: bytes,
) -> list[ClipCandidate]:
    """Normalize untrusted word-span proposals into measured clip timings.

    External models propose word indices only. Workflow OS resolves those indices
    against measured transcript timings instead of trusting model-generated time
    arithmetic. Rights, campaign compliance, QC and publication authority remain
    outside this boundary.
    """

    by_index = _validate_words(words)
    materialized = list(proposals)
    if not 1 <= len(materialized) <= _MAX_PROPOSALS:
        raise ValueError(f"proposals must contain 1..{_MAX_PROPOSALS} values")
    digest = evidence_digest_for_analysis(analysis_evidence)

    candidates: list[ClipCandidate] = []
    seen_ids: set[str] = set()
    for proposal in materialized:
        if not isinstance(proposal, WordSpanProposal):
            raise ValueError("proposals must contain WordSpanProposal values")
        candidate_id = _candidate_id(proposal.candidate_id)
        if candidate_id in seen_ids:
            raise ValueError("candidate_id values must be unique")
        seen_ids.add(candidate_id)

        start_index = _bounded_int(
            proposal.start_word_index,
            "start_word_index",
            0,
            len(by_index) - 1,
        )
        end_index = _bounded_int(
            proposal.end_word_index,
            "end_word_index",
            0,
            len(by_index) - 1,
        )
        if end_index < start_index:
            raise ValueError("end_word_index must be >= start_word_index")

        start_ms = by_index[start_index].start_ms
        end_ms = by_index[end_index].end_ms
        candidates.append(
            ClipCandidate(
                candidate_id=candidate_id,
                start_ms=start_ms,
                duration_ms=end_ms - start_ms,
                hook_score=_unit_score(proposal.hook_score, "hook_score"),
                relevance_score=_unit_score(proposal.relevance_score, "relevance_score"),
                quality_score=_unit_score(proposal.quality_score, "quality_score"),
                analysis_evidence_sha256=digest,
            )
        )
    return candidates
