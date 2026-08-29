from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_MAX_RANGE_HEADER_CHARS = 128
_STATE_INCOMPLETE = "INCOMPLETE"
_STATE_SESSION_EXPIRED = "SESSION_EXPIRED"
_STATE_COMPLETE_NEEDS_PROCESSING_VERIFY = "COMPLETE_NEEDS_PROCESSING_VERIFY"
_STATE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class YouTubeResumableRecoveryEvidence:
    state: str
    next_byte: int | None
    restart_required: bool
    processing_verification_required: bool


def _validate_total_size(total_size: int) -> int:
    if not isinstance(total_size, int) or isinstance(total_size, bool) or total_size <= 0:
        raise ValueError("total_size must be a positive integer")
    return total_size


def _get_range_header(headers: Mapping[str, str]) -> str | None:
    if not isinstance(headers, Mapping):
        raise TypeError("headers must be a mapping")
    found: str | None = None
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise TypeError("response headers must contain strings")
        if raw_name.lower() != "range":
            continue
        if found is not None:
            raise ValueError("duplicate YouTube Range response header")
        value = raw_value.strip()
        if not value or len(value) > _MAX_RANGE_HEADER_CHARS:
            raise ValueError("YouTube Range response header is malformed")
        found = value
    return found


def _next_byte_from_range(value: str, *, total_size: int) -> int:
    prefix = "bytes=0-"
    if not value.startswith(prefix):
        raise ValueError("YouTube Range response header is malformed")
    terminal_text = value[len(prefix) :]
    if not terminal_text or not terminal_text.isascii() or not terminal_text.isdigit():
        raise ValueError("YouTube Range response header is malformed")
    terminal = int(terminal_text)
    if terminal < 0 or terminal >= total_size:
        raise ValueError("YouTube Range response exceeds expected asset size")
    next_byte = terminal + 1
    if next_byte >= total_size:
        raise ValueError("308 response cannot claim the entire upload is complete")
    return next_byte


def parse_resumable_recovery_response(
    status_code: int,
    headers: Mapping[str, str],
    *,
    total_size: int,
) -> YouTubeResumableRecoveryEvidence:
    """Classify an official resumable-upload recovery response without guessing state.

    This parser grants no publication or revenue authority. A terminal 2xx only proves
    that upload transport completed; video processing must still be independently
    verified before publication provenance becomes terminal.
    """

    if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
        raise ValueError("status_code must be an HTTP status integer")
    size = _validate_total_size(total_size)
    range_header = _get_range_header(headers)

    if status_code == 308:
        next_byte = 0 if range_header is None else _next_byte_from_range(range_header, total_size=size)
        return YouTubeResumableRecoveryEvidence(
            state=_STATE_INCOMPLETE,
            next_byte=next_byte,
            restart_required=False,
            processing_verification_required=False,
        )

    if range_header is not None:
        raise ValueError("Range response header is only trusted for HTTP 308 recovery evidence")

    if status_code == 404:
        return YouTubeResumableRecoveryEvidence(
            state=_STATE_SESSION_EXPIRED,
            next_byte=None,
            restart_required=True,
            processing_verification_required=False,
        )

    if 200 <= status_code <= 299:
        return YouTubeResumableRecoveryEvidence(
            state=_STATE_COMPLETE_NEEDS_PROCESSING_VERIFY,
            next_byte=None,
            restart_required=False,
            processing_verification_required=True,
        )

    return YouTubeResumableRecoveryEvidence(
        state=_STATE_UNKNOWN,
        next_byte=None,
        restart_required=False,
        processing_verification_required=False,
    )
