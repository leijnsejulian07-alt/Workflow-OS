from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from workflow_os.adapters.tiktok_direct_post import (
    TikTokDirectPostOptions,
    build_status_request,
    build_upload_request,
    build_video_init_request,
    parse_status_response,
    parse_video_init_response,
    plan_file_upload,
)
from workflow_os.adapters.tiktok_http_transport import (
    TikTokHttpTransport,
    read_verified_chunk,
    verify_local_asset,
)
from workflow_os.submission_execution import SubmissionAttemptResult
from workflow_os.submissions import SubmissionRequest


@dataclass(frozen=True)
class TikTokPollingPolicy:
    """Bounded status polling policy; sleeping is injected by the caller."""

    max_polls: int = 8
    interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_polls, int) or isinstance(self.max_polls, bool):
            raise TypeError("max_polls must be an integer")
        if not 1 <= self.max_polls <= 30:
            raise ValueError("max_polls must be between 1 and 30")
        if not isinstance(self.interval_seconds, (int, float)) or isinstance(self.interval_seconds, bool):
            raise TypeError("interval_seconds must be numeric")
        if not 1.0 <= float(self.interval_seconds) <= 60.0:
            raise ValueError("interval_seconds must be between 1 and 60 seconds")


def execute_tiktok_direct_post_attempt(
    request: SubmissionRequest,
    *,
    options: TikTokDirectPostOptions,
    access_token: str,
    asset_root: str | Path,
    transport: TikTokHttpTransport,
    polling: TikTokPollingPolicy = TikTokPollingPolicy(),
    sleep: Callable[[float], None],
) -> SubmissionAttemptResult:
    """Execute one bounded official TikTok Direct Post attempt.

    This function deliberately performs no retries. Any exception after dispatch may
    represent an ambiguous external side effect and must be reconciled by the caller's
    SideEffectLedger as UNKNOWN. Only TikTok's terminal status can produce APPLIED or
    NOT_APPLIED.
    """

    if not isinstance(request, SubmissionRequest):
        raise TypeError("request must be a SubmissionRequest")
    if not isinstance(options, TikTokDirectPostOptions):
        raise TypeError("options must be TikTokDirectPostOptions")
    if not isinstance(transport, TikTokHttpTransport):
        raise TypeError("transport must be TikTokHttpTransport")
    if not callable(sleep):
        raise TypeError("sleep must be callable")

    verified_asset = verify_local_asset(asset_root, request.asset)
    init_request = build_video_init_request(request, options=options, access_token=access_token)
    init_result = parse_video_init_response(transport.post_json(init_request))

    upload_plan = plan_file_upload(verified_asset.size_bytes)
    for index, chunk in enumerate(upload_plan.chunks):
        upload_request = build_upload_request(
            init_result.upload_url,
            media_type=request.asset.media_type,
            chunk=chunk,
        )
        data = read_verified_chunk(verified_asset, upload_request)
        transport.put_chunk(
            upload_request,
            data=data,
            is_final_chunk=index == len(upload_plan.chunks) - 1,
        )

    status_request = build_status_request(publish_id=init_result.publish_id, access_token=access_token)
    for poll_index in range(polling.max_polls):
        status = parse_status_response(transport.post_json(status_request))
        if status.terminal:
            if status.succeeded:
                if not status.post_ids:
                    return SubmissionAttemptResult(outcome="UNKNOWN")
                return SubmissionAttemptResult(
                    outcome="APPLIED",
                    external_reference=f"tiktok:{status.post_ids[0]}",
                )
            return SubmissionAttemptResult(outcome="NOT_APPLIED")
        if poll_index + 1 < polling.max_polls:
            sleep(float(polling.interval_seconds))

    return SubmissionAttemptResult(outcome="UNKNOWN")
