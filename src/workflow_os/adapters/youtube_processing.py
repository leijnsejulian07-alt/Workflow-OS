from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_MAX_VIDEO_ID_CHARS = 128
_STATE_SUCCEEDED = "SUCCEEDED"
_STATE_PROCESSING = "PROCESSING"
_STATE_FAILED = "FAILED"
_STATE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class YouTubeProcessingEvidence:
    state: str
    video_id: str
    upload_status: str | None
    processing_status: str | None
    failure_reason: str | None
    terminal_publication_verified: bool


def _clean_video_id(value: str, field: str = "YouTube video id") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > _MAX_VIDEO_ID_CHARS
        or not cleaned.isascii()
        or any(ch.isspace() for ch in cleaned)
        or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in cleaned)
    ):
        raise ValueError(f"{field} is malformed")
    return cleaned


def parse_terminal_upload_video_id(payload: Mapping[str, object]) -> str:
    """Extract a bounded video ID from a terminal videos.insert response.

    A returned ID proves identity only. It grants no publication or revenue authority;
    videos.list processing evidence must still independently verify completion.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("terminal YouTube upload payload must be a mapping")
    if "id" not in payload:
        raise ValueError("terminal YouTube upload response is missing video id")
    return _clean_video_id(payload["id"], "terminal YouTube video id")  # type: ignore[arg-type]


def _optional_text(mapping: Mapping[str, object], key: str, *, maximum: int = 128) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"YouTube {key} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or not cleaned.isascii():
        raise ValueError(f"YouTube {key} is malformed")
    return cleaned


def parse_video_processing_response(
    payload: Mapping[str, object],
    *,
    expected_video_id: str,
) -> YouTubeProcessingEvidence:
    """Fail-closed parser for videos.list(status,processingDetails) evidence."""

    expected = _clean_video_id(expected_video_id, "expected YouTube video id")
    if not isinstance(payload, Mapping):
        raise TypeError("YouTube videos.list payload must be a mapping")
    items = payload.get("items")
    if not isinstance(items, list):
        raise TypeError("YouTube videos.list items must be a list")
    if len(items) != 1:
        raise ValueError("YouTube videos.list must return exactly one video")

    item = items[0]
    if not isinstance(item, Mapping):
        raise TypeError("YouTube videos.list item must be a mapping")
    video_id = _clean_video_id(item.get("id"), "returned YouTube video id")  # type: ignore[arg-type]
    if video_id != expected:
        raise ValueError("YouTube videos.list returned unexpected video id")

    status = item.get("status")
    processing = item.get("processingDetails")
    if not isinstance(status, Mapping) or not isinstance(processing, Mapping):
        raise TypeError("YouTube processing evidence is missing status or processingDetails")

    upload_status = _optional_text(status, "uploadStatus")
    processing_status = _optional_text(processing, "processingStatus")
    failure_reason = _optional_text(processing, "processingFailureReason")

    if processing_status == "failed":
        if failure_reason is None:
            raise ValueError("failed YouTube processing is missing failure reason")
        return YouTubeProcessingEvidence(
            state=_STATE_FAILED,
            video_id=video_id,
            upload_status=upload_status,
            processing_status=processing_status,
            failure_reason=failure_reason,
            terminal_publication_verified=False,
        )
    if failure_reason is not None:
        raise ValueError("YouTube processing failure reason conflicts with non-failed status")
    if upload_status in {"deleted", "failed", "rejected"}:
        return YouTubeProcessingEvidence(
            state=_STATE_FAILED,
            video_id=video_id,
            upload_status=upload_status,
            processing_status=processing_status,
            failure_reason=None,
            terminal_publication_verified=False,
        )
    if upload_status == "processed" and processing_status == "succeeded":
        return YouTubeProcessingEvidence(
            state=_STATE_SUCCEEDED,
            video_id=video_id,
            upload_status=upload_status,
            processing_status=processing_status,
            failure_reason=None,
            terminal_publication_verified=True,
        )
    if upload_status in {"uploaded", "processed"} and processing_status == "processing":
        return YouTubeProcessingEvidence(
            state=_STATE_PROCESSING,
            video_id=video_id,
            upload_status=upload_status,
            processing_status=processing_status,
            failure_reason=None,
            terminal_publication_verified=False,
        )
    return YouTubeProcessingEvidence(
        state=_STATE_UNKNOWN,
        video_id=video_id,
        upload_status=upload_status,
        processing_status=processing_status,
        failure_reason=None,
        terminal_publication_verified=False,
    )
