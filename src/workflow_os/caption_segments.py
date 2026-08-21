from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .word_index_highlights import WordTiming

_MAX_WORDS = 200_000
_MAX_TEXT_CHARS = 500_000
_MAX_SEGMENTS = 20_000
_MAX_WORDS_PER_SEGMENT = 12
_MAX_CHARS_PER_SEGMENT = 80
_MAX_SEGMENT_MS = 8_000


@dataclass(frozen=True)
class TranscriptWord:
    timing: WordTiming
    text: str


@dataclass(frozen=True)
class CaptionSegment:
    start_ms: int
    end_ms: int
    text: str
    start_word_index: int
    end_word_index: int


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("word text must be a string")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 200:
        raise ValueError("word text must contain 1..200 normalized characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError("word text contains control characters")
    return cleaned


def _validate_words(words: Iterable[TranscriptWord]) -> list[TranscriptWord]:
    materialized = list(words)
    if not 1 <= len(materialized) <= _MAX_WORDS:
        raise ValueError(f"words must contain 1..{_MAX_WORDS} values")

    validated: list[TranscriptWord] = []
    previous_end = -1
    total_chars = 0
    for expected_index, word in enumerate(materialized):
        if not isinstance(word, TranscriptWord):
            raise ValueError("words must contain TranscriptWord values")
        if not isinstance(word.timing, WordTiming):
            raise ValueError("timing must be WordTiming")
        index = _bounded_int(word.timing.word_index, "word_index", 0, _MAX_WORDS - 1)
        start_ms = _bounded_int(word.timing.start_ms, "start_ms", 0, 24 * 60 * 60 * 1000)
        end_ms = _bounded_int(word.timing.end_ms, "end_ms", 1, 24 * 60 * 60 * 1000)
        if index != expected_index:
            raise ValueError("word_index values must be contiguous and zero-based")
        if end_ms <= start_ms:
            raise ValueError("word timing end_ms must be greater than start_ms")
        if start_ms < previous_end:
            raise ValueError("word timings must be monotonic and non-overlapping")
        text = _clean_text(word.text)
        total_chars += len(text)
        if total_chars > _MAX_TEXT_CHARS:
            raise ValueError("transcript text exceeds allowed size")
        validated.append(TranscriptWord(WordTiming(index, start_ms, end_ms), text))
        previous_end = end_ms
    return validated


def plan_caption_segments(
    words: Iterable[TranscriptWord],
    *,
    clip_start_ms: int,
    clip_duration_ms: int,
    max_words_per_segment: int = 6,
    max_chars_per_segment: int = 42,
    max_segment_ms: int = 3_000,
) -> list[CaptionSegment]:
    """Create deterministic caption segments from measured word timing.

    This layer performs no transcription, AI inference, rendering, rights
    inference or publication. Segment timing is derived only from validated
    measured word timings and clipped to the selected source interval.
    """

    clip_start_ms = _bounded_int(clip_start_ms, "clip_start_ms", 0, 24 * 60 * 60 * 1000)
    clip_duration_ms = _bounded_int(clip_duration_ms, "clip_duration_ms", 250, 3 * 60 * 1000)
    max_words_per_segment = _bounded_int(
        max_words_per_segment, "max_words_per_segment", 1, _MAX_WORDS_PER_SEGMENT
    )
    max_chars_per_segment = _bounded_int(
        max_chars_per_segment, "max_chars_per_segment", 1, _MAX_CHARS_PER_SEGMENT
    )
    max_segment_ms = _bounded_int(max_segment_ms, "max_segment_ms", 250, _MAX_SEGMENT_MS)

    validated = _validate_words(words)
    clip_end_ms = clip_start_ms + clip_duration_ms
    selected = [
        word
        for word in validated
        if word.timing.end_ms > clip_start_ms and word.timing.start_ms < clip_end_ms
    ]
    if not selected:
        raise ValueError("clip interval does not contain transcript words")

    segments: list[CaptionSegment] = []
    current: list[TranscriptWord] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        start = max(current[0].timing.start_ms, clip_start_ms) - clip_start_ms
        end = min(current[-1].timing.end_ms, clip_end_ms) - clip_start_ms
        if end <= start:
            raise ValueError("caption segment duration must be positive")
        segments.append(
            CaptionSegment(
                start_ms=start,
                end_ms=end,
                text=" ".join(item.text for item in current),
                start_word_index=current[0].timing.word_index,
                end_word_index=current[-1].timing.word_index,
            )
        )
        current = []

    for word in selected:
        proposed = current + [word]
        proposed_text = " ".join(item.text for item in proposed)
        proposed_start = max(proposed[0].timing.start_ms, clip_start_ms)
        proposed_end = min(proposed[-1].timing.end_ms, clip_end_ms)
        exceeds = (
            len(proposed) > max_words_per_segment
            or len(proposed_text) > max_chars_per_segment
            or proposed_end - proposed_start > max_segment_ms
        )
        if exceeds and current:
            flush()
            proposed = [word]
            proposed_text = word.text
            proposed_start = max(word.timing.start_ms, clip_start_ms)
            proposed_end = min(word.timing.end_ms, clip_end_ms)
        if len(proposed_text) > max_chars_per_segment:
            raise ValueError("single word exceeds caption character limit")
        if proposed_end - proposed_start > max_segment_ms:
            raise ValueError("single word exceeds caption duration limit")
        current = proposed

    flush()
    if not 1 <= len(segments) <= _MAX_SEGMENTS:
        raise ValueError("caption segment count is outside allowed bounds")
    return segments
