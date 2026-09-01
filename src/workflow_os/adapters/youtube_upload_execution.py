from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from workflow_os.adapters.youtube_http_transport import YouTubeHttpTransport
from workflow_os.adapters.youtube_processing import (
    parse_terminal_upload_video_id,
    parse_video_processing_response,
)
from workflow_os.adapters.youtube_upload import (
    YouTubeUploadOptions,
    build_resumable_init_request,
    build_upload_request,
    build_video_status_request,
)
from workflow_os.adapters.youtube_upload_recovery import parse_resumable_recovery_response
from workflow_os.submission_execution import SubmissionAttemptResult
from workflow_os.submissions import SubmissionRequest

_CHUNK_GRANULARITY = 256 * 1024
_DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
_HASH_BLOCK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class YouTubePollingPolicy:
    max_polls: int = 12
    interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_polls, int) or isinstance(self.max_polls, bool):
            raise TypeError("max_polls must be an integer")
        if not 1 <= self.max_polls <= 60:
            raise ValueError("max_polls must be between 1 and 60")
        if not isinstance(self.interval_seconds, (int, float)) or isinstance(self.interval_seconds, bool):
            raise TypeError("interval_seconds must be numeric")
        if not 1.0 <= float(self.interval_seconds) <= 300.0:
            raise ValueError("interval_seconds must be between 1 and 300 seconds")


def _verified_path(asset_root: str | Path, request: SubmissionRequest) -> tuple[Path, int]:
    root = Path(asset_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("asset root must be a directory")
    candidate = (root / request.asset.path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("submission asset resolves outside the configured asset root") from exc
    if not candidate.is_file():
        raise ValueError("submission asset must resolve to a regular file")
    stat = candidate.stat()
    if stat.st_size != request.asset.size_bytes:
        raise ValueError("submission asset size no longer matches verified evidence")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK_BYTES), b""):
            digest.update(block)
    if digest.hexdigest() != request.asset.sha256.strip().lower():
        raise ValueError("submission asset digest no longer matches verified evidence")
    return candidate, stat.st_mtime_ns


def _read_chunk(path: Path, *, expected_size: int, expected_mtime_ns: int, start: int, end: int) -> bytes:
    expected = end - start + 1
    with path.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        if stat.st_size != expected_size or stat.st_mtime_ns != expected_mtime_ns:
            raise ValueError("submission asset changed after verification")
        handle.seek(start)
        data = handle.read(expected)
    if len(data) != expected:
        raise ValueError("submission asset did not contain the requested byte range")
    return data


def _terminal_video_id(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("terminal YouTube upload response is malformed JSON") from exc
    return parse_terminal_upload_video_id(payload)


def execute_youtube_upload_attempt(
    request: SubmissionRequest,
    *,
    options: YouTubeUploadOptions,
    access_token: str,
    asset_root: str | Path,
    transport: YouTubeHttpTransport,
    polling: YouTubePollingPolicy = YouTubePollingPolicy(),
    sleep: Callable[[float], None],
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> SubmissionAttemptResult:
    """Execute one bounded official YouTube resumable-upload attempt.

    No retry is performed after ambiguous network state. Only terminal videos.list
    processing evidence can return APPLIED; upload completion alone is insufficient.
    """
    if not isinstance(request, SubmissionRequest):
        raise TypeError("request must be a SubmissionRequest")
    if not isinstance(options, YouTubeUploadOptions):
        raise TypeError("options must be YouTubeUploadOptions")
    if not isinstance(transport, YouTubeHttpTransport):
        raise TypeError("transport must be YouTubeHttpTransport")
    if not callable(sleep):
        raise TypeError("sleep must be callable")
    if (
        not isinstance(chunk_size, int)
        or isinstance(chunk_size, bool)
        or chunk_size <= 0
        or chunk_size % _CHUNK_GRANULARITY
    ):
        raise ValueError("chunk_size must be a positive multiple of 256 KB")

    path, mtime_ns = _verified_path(asset_root, request)
    init = build_resumable_init_request(request, options=options, access_token=access_token)
    session = transport.initialize(init)
    total = request.asset.size_bytes
    video_id: str | None = None

    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total) - 1
        upload = build_upload_request(
            session.session_url,
            access_token=access_token,
            media_type=request.asset.media_type,
            total_size=total,
            start_byte=start,
            end_byte=end,
            chunk_size=chunk_size,
        )
        data = _read_chunk(
            path,
            expected_size=total,
            expected_mtime_ns=mtime_ns,
            start=start,
            end=end,
        )
        response = transport.upload_chunk(upload, data)
        evidence = parse_resumable_recovery_response(
            response.status_code,
            response.headers,
            total_size=total,
        )
        if response.status_code == 308:
            if evidence.next_byte != end + 1:
                return SubmissionAttemptResult(outcome="UNKNOWN")
            continue
        if 200 <= response.status_code <= 299:
            if end != total - 1:
                return SubmissionAttemptResult(outcome="UNKNOWN")
            video_id = _terminal_video_id(response.body)
            break
        return SubmissionAttemptResult(outcome="UNKNOWN")

    if video_id is None:
        return SubmissionAttemptResult(outcome="UNKNOWN")

    status_request = build_video_status_request(video_id, access_token=access_token)
    for poll_index in range(polling.max_polls):
        evidence = parse_video_processing_response(
            transport.fetch_processing(status_request),
            expected_video_id=video_id,
        )
        if evidence.state == "SUCCEEDED" and evidence.terminal_publication_verified:
            return SubmissionAttemptResult(
                outcome="APPLIED",
                external_reference=f"youtube:{video_id}",
            )
        if evidence.state == "FAILED":
            return SubmissionAttemptResult(outcome="NOT_APPLIED")
        if evidence.state == "UNKNOWN":
            return SubmissionAttemptResult(outcome="UNKNOWN")
        if poll_index + 1 < polling.max_polls:
            sleep(float(polling.interval_seconds))
    return SubmissionAttemptResult(outcome="UNKNOWN")
