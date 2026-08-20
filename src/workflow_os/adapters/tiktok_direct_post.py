from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from workflow_os.submissions import SubmissionRequest


TIKTOK_API_HOST = "open.tiktokapis.com"
TIKTOK_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_ALLOWED_PRIVACY_LEVELS = frozenset(
    {
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "FOLLOWER_OF_CREATOR",
        "SELF_ONLY",
    }
)
_ALLOWED_VIDEO_MEDIA_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
_MIN_CHUNK_BYTES = 5 * 1024 * 1024
_MAX_CHUNK_BYTES = 64 * 1024 * 1024
_MAX_FINAL_CHUNK_BYTES = 128 * 1024 * 1024
_MAX_CHUNKS = 1000
_PROCESSING_STATUSES = frozenset({"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"})


@dataclass(frozen=True)
class TikTokCreatorSnapshot:
    """Evidence captured from TikTok's creator_info/query step."""

    privacy_level_options: tuple[str, ...]
    verified: bool


@dataclass(frozen=True)
class TikTokDirectPostOptions:
    privacy_level: str
    creator_snapshot: TikTokCreatorSnapshot
    explicit_user_consent: bool
    client_audited: bool
    is_aigc: bool = False


@dataclass(frozen=True)
class TikTokInitRequest:
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]


@dataclass(frozen=True)
class TikTokInitResult:
    publish_id: str
    upload_url: str


@dataclass(frozen=True)
class TikTokUploadChunk:
    index: int
    start_byte: int
    end_byte: int
    size_bytes: int
    content_range: str


@dataclass(frozen=True)
class TikTokUploadPlan:
    video_size: int
    chunk_size: int
    total_chunk_count: int
    chunks: tuple[TikTokUploadChunk, ...]


@dataclass(frozen=True)
class TikTokUploadRequest:
    url: str
    headers: Mapping[str, str]
    start_byte: int
    end_byte: int


@dataclass(frozen=True)
class TikTokStatusRequest:
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]


@dataclass(frozen=True)
class TikTokPostStatus:
    status: str
    terminal: bool
    succeeded: bool
    fail_reason: str | None
    post_ids: tuple[str, ...]
    uploaded_bytes: int | None


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _validate_access_token(access_token: str) -> str:
    if not isinstance(access_token, str):
        raise TypeError("TikTok access token must be a string")
    token = access_token.strip()
    if not token or len(token) > 4096 or any(ch.isspace() for ch in token):
        raise ValueError("TikTok access token is missing or malformed")
    return token


def _validate_publish_id(publish_id: str) -> str:
    if not isinstance(publish_id, str):
        raise TypeError("TikTok publish_id must be a string")
    value = publish_id.strip()
    if not value or len(value) > 64 or any(ch.isspace() for ch in value):
        raise ValueError("TikTok publish_id is missing or malformed")
    return value


def _validate_upload_url(upload_url: str) -> str:
    if not isinstance(upload_url, str) or len(upload_url) > 256:
        raise ValueError("TikTok upload URL is missing or too long")
    parsed = urlparse(upload_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "open-upload.tiktokapis.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/")
    ):
        raise ValueError("TikTok upload URL has an unexpected origin")
    return upload_url


def plan_file_upload(video_size: int) -> TikTokUploadPlan:
    """Create TikTok's sequential FILE_UPLOAD chunk plan without reading the file."""

    if not isinstance(video_size, int) or isinstance(video_size, bool) or video_size <= 0:
        raise ValueError("TikTok video size must be a positive integer")

    if video_size <= _MAX_CHUNK_BYTES:
        chunk_size = video_size
        count = 1
    else:
        chunk_size = _MAX_CHUNK_BYTES
        count = video_size // chunk_size
        if count < 1 or count > _MAX_CHUNKS:
            raise ValueError("TikTok video requires an unsupported number of chunks")

    chunks: list[TikTokUploadChunk] = []
    for index in range(count):
        start = index * chunk_size
        end = video_size - 1 if index == count - 1 else start + chunk_size - 1
        size = end - start + 1
        if count > 1 and index < count - 1 and not (_MIN_CHUNK_BYTES <= size <= _MAX_CHUNK_BYTES):
            raise ValueError("TikTok non-final chunk is outside allowed size limits")
        if index == count - 1 and size > _MAX_FINAL_CHUNK_BYTES:
            raise ValueError("TikTok final chunk is outside allowed size limits")
        chunks.append(
            TikTokUploadChunk(
                index=index,
                start_byte=start,
                end_byte=end,
                size_bytes=size,
                content_range=f"bytes {start}-{end}/{video_size}",
            )
        )

    return TikTokUploadPlan(
        video_size=video_size,
        chunk_size=chunk_size,
        total_chunk_count=count,
        chunks=tuple(chunks),
    )


def build_video_init_request(
    request: SubmissionRequest,
    *,
    options: TikTokDirectPostOptions,
    access_token: str,
) -> TikTokInitRequest:
    """Build the official Direct Post video-init request without performing I/O."""

    if not request.account_authorized:
        raise ValueError("submission account is not authorized")
    if not request.rights_verified:
        raise ValueError("submission rights are not verified")
    if not request.disclosure_satisfied:
        raise ValueError("submission disclosure requirements are not satisfied")
    if not request.campaign_requirements_verified:
        raise ValueError("campaign requirements are not verified")

    if request.asset.media_type not in _ALLOWED_VIDEO_MEDIA_TYPES:
        raise ValueError("unsupported TikTok Direct Post video media type")
    if _utf16_units(request.caption) > 2200:
        raise ValueError("TikTok caption exceeds 2200 UTF-16 code units")

    if not options.creator_snapshot.verified:
        raise ValueError("TikTok creator info has not been verified")
    if not options.explicit_user_consent:
        raise ValueError("TikTok Direct Post requires explicit user consent")

    privacy = options.privacy_level.strip() if isinstance(options.privacy_level, str) else ""
    if privacy not in _ALLOWED_PRIVACY_LEVELS:
        raise ValueError("unsupported TikTok privacy level")
    creator_options = set(options.creator_snapshot.privacy_level_options)
    if privacy not in creator_options:
        raise ValueError("privacy level is not present in latest creator info")
    if not options.client_audited and privacy != "SELF_ONLY":
        raise ValueError("unaudited TikTok clients must fail closed to SELF_ONLY")

    token = _validate_access_token(access_token)
    upload_plan = plan_file_upload(request.asset.size_bytes)
    body = {
        "post_info": {
            "title": request.caption,
            "privacy_level": privacy,
            "is_aigc": bool(options.is_aigc),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": upload_plan.video_size,
            "chunk_size": upload_plan.chunk_size,
            "total_chunk_count": upload_plan.total_chunk_count,
        },
    }
    return TikTokInitRequest(
        url=TIKTOK_VIDEO_INIT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json_body=body,
    )


def parse_video_init_response(payload: Mapping[str, Any]) -> TikTokInitResult:
    """Parse a TikTok init response fail closed before any media upload begins."""

    if not isinstance(payload, Mapping):
        raise TypeError("TikTok init response must be an object")
    error = payload.get("error")
    if not isinstance(error, Mapping) or error.get("code") != "ok":
        raise ValueError("TikTok init response did not confirm success")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("TikTok init response is missing data")

    publish_id = _validate_publish_id(data.get("publish_id"))
    upload_url = _validate_upload_url(data.get("upload_url"))
    return TikTokInitResult(publish_id=publish_id, upload_url=upload_url)


def build_upload_request(
    upload_url: str,
    *,
    media_type: str,
    chunk: TikTokUploadChunk,
) -> TikTokUploadRequest:
    """Build one sequential media-transfer PUT request; caller supplies exact bytes."""

    url = _validate_upload_url(upload_url)
    if media_type not in _ALLOWED_VIDEO_MEDIA_TYPES:
        raise ValueError("unsupported TikTok upload media type")
    if not isinstance(chunk, TikTokUploadChunk):
        raise TypeError("chunk must be a TikTokUploadChunk")
    if chunk.size_bytes != chunk.end_byte - chunk.start_byte + 1 or chunk.size_bytes <= 0:
        raise ValueError("TikTok chunk byte range is inconsistent")
    return TikTokUploadRequest(
        url=url,
        headers={
            "Content-Type": media_type,
            "Content-Length": str(chunk.size_bytes),
            "Content-Range": chunk.content_range,
        },
        start_byte=chunk.start_byte,
        end_byte=chunk.end_byte,
    )


def parse_upload_response(http_status: int, *, is_final_chunk: bool) -> bool:
    """Return True only when TikTok confirms the expected chunk-transfer state."""

    expected = 201 if is_final_chunk else 206
    if http_status != expected:
        raise ValueError("TikTok upload response did not confirm expected chunk progress")
    return True


def build_status_request(*, publish_id: str, access_token: str) -> TikTokStatusRequest:
    token = _validate_access_token(access_token)
    pid = _validate_publish_id(publish_id)
    return TikTokStatusRequest(
        url=TIKTOK_STATUS_FETCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json_body={"publish_id": pid},
    )


def parse_status_response(payload: Mapping[str, Any]) -> TikTokPostStatus:
    """Normalize TikTok post status without treating in-progress work as success."""

    if not isinstance(payload, Mapping):
        raise TypeError("TikTok status response must be an object")
    error = payload.get("error")
    if not isinstance(error, Mapping) or error.get("code") != "ok":
        raise ValueError("TikTok status response did not confirm success")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("TikTok status response is missing data")

    status = data.get("status")
    allowed_statuses = _PROCESSING_STATUSES | {"PUBLISH_COMPLETE", "FAILED"}
    if not isinstance(status, str) or status not in allowed_statuses:
        raise ValueError("TikTok status response contains an unknown state")

    uploaded_bytes = data.get("uploaded_bytes")
    if uploaded_bytes is not None and (
        not isinstance(uploaded_bytes, int) or isinstance(uploaded_bytes, bool) or uploaded_bytes < 0
    ):
        raise ValueError("TikTok status uploaded_bytes is invalid")

    raw_post_ids = data.get("publicaly_available_post_id", [])
    if not isinstance(raw_post_ids, list) or len(raw_post_ids) > 100:
        raise ValueError("TikTok status post ID list is invalid")
    post_ids: list[str] = []
    for value in raw_post_ids:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("TikTok status contains an invalid post ID")
        text = str(value).strip()
        if not text or len(text) > 64 or not text.isdigit():
            raise ValueError("TikTok status contains an invalid post ID")
        post_ids.append(text)

    fail_reason = data.get("fail_reason")
    if fail_reason is not None:
        if not isinstance(fail_reason, str) or not fail_reason.strip() or len(fail_reason) > 256:
            raise ValueError("TikTok status fail_reason is invalid")
        fail_reason = fail_reason.strip()

    if status == "FAILED" and fail_reason is None:
        raise ValueError("TikTok FAILED status is missing fail_reason")
    if status != "FAILED" and fail_reason is not None:
        raise ValueError("TikTok non-failed status unexpectedly includes fail_reason")

    return TikTokPostStatus(
        status=status,
        terminal=status in {"PUBLISH_COMPLETE", "FAILED"},
        succeeded=status == "PUBLISH_COMPLETE",
        fail_reason=fail_reason,
        post_ids=tuple(post_ids),
        uploaded_bytes=uploaded_bytes,
    )
