from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlencode, urlparse

from workflow_os.submissions import SubmissionRequest


YOUTUBE_UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_VIDEO_STATUS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_ALLOWED_VIDEO_MEDIA_TYPES = frozenset({"video/mp4", "video/webm"})
_ALLOWED_PRIVACY = frozenset({"private", "unlisted", "public"})
_MAX_TITLE_CHARS = 100
_MAX_DESCRIPTION_BYTES = 5000
_MAX_TOKEN_CHARS = 4096
_MAX_SESSION_URL_CHARS = 4096
_MAX_CATEGORY_ID_CHARS = 16
_RESUMABLE_CHUNK_GRANULARITY = 256 * 1024


@dataclass(frozen=True)
class YouTubeProjectEvidence:
    api_project_verified: bool
    owned_channel_verified: bool
    upload_scope_verified: bool


@dataclass(frozen=True)
class YouTubeUploadOptions:
    title: str
    description: str
    category_id: str
    category_id_verified: bool
    privacy_status: str
    self_declared_made_for_kids: bool
    project_evidence: YouTubeProjectEvidence


@dataclass(frozen=True)
class YouTubeInitRequest:
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, object]


@dataclass(frozen=True)
class YouTubeUploadRequest:
    url: str
    headers: Mapping[str, str]
    start_byte: int
    end_byte: int


@dataclass(frozen=True)
class YouTubeUploadStatusProbe:
    url: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class YouTubeStatusRequest:
    url: str
    headers: Mapping[str, str]


def _clean_token(access_token: str) -> str:
    if not isinstance(access_token, str):
        raise TypeError("YouTube access token must be a string")
    token = access_token.strip()
    if not token or len(token) > _MAX_TOKEN_CHARS or any(ch.isspace() for ch in token):
        raise ValueError("YouTube access token is missing or malformed")
    return token


def _clean_text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} is missing or too long")
    return cleaned


def _clean_category_id(category_id: str, *, verified: bool) -> str:
    if not isinstance(verified, bool):
        raise TypeError("YouTube category verification flag must be boolean")
    if not verified:
        raise ValueError("YouTube category id is not verified")
    value = _clean_text(category_id, "YouTube category id", _MAX_CATEGORY_ID_CHARS)
    if not value.isascii() or not value.isdigit():
        raise ValueError("YouTube category id is malformed")
    return value


def _validate_session_url(session_url: str) -> str:
    if not isinstance(session_url, str) or not session_url or len(session_url) > _MAX_SESSION_URL_CHARS:
        raise ValueError("YouTube resumable session URL is missing or too long")
    parsed = urlparse(session_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.googleapis.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path != "/upload/youtube/v3/videos"
        or parsed.fragment
    ):
        raise ValueError("YouTube resumable session URL has an unexpected origin")
    return session_url


def _validate_total_size(total_size: int) -> int:
    if not isinstance(total_size, int) or isinstance(total_size, bool) or total_size <= 0:
        raise ValueError("total_size must be a positive integer")
    return total_size


def build_resumable_init_request(
    request: SubmissionRequest,
    *,
    options: YouTubeUploadOptions,
    access_token: str,
) -> YouTubeInitRequest:
    """Build YouTube's official resumable-upload initialization request without I/O."""

    if not isinstance(request, SubmissionRequest):
        raise TypeError("request must be SubmissionRequest")
    if not request.account_authorized:
        raise ValueError("submission account is not authorized")
    if not request.rights_verified:
        raise ValueError("submission rights are not verified")
    if not request.disclosure_satisfied:
        raise ValueError("submission disclosure requirements are not satisfied")
    if not request.campaign_requirements_verified:
        raise ValueError("campaign requirements are not verified")
    if request.asset.media_type not in _ALLOWED_VIDEO_MEDIA_TYPES:
        raise ValueError("unsupported YouTube video media type")
    if not isinstance(options.project_evidence, YouTubeProjectEvidence):
        raise TypeError("project evidence must be YouTubeProjectEvidence")
    if not options.project_evidence.owned_channel_verified:
        raise ValueError("owned YouTube channel identity is not verified")
    if not options.project_evidence.upload_scope_verified:
        raise ValueError("least-privilege YouTube upload scope is not verified")
    if not isinstance(options.self_declared_made_for_kids, bool):
        raise TypeError("self_declared_made_for_kids must be boolean")

    privacy = options.privacy_status.strip() if isinstance(options.privacy_status, str) else ""
    if privacy not in _ALLOWED_PRIVACY:
        raise ValueError("unsupported YouTube privacy status")
    if privacy != "private" and not options.project_evidence.api_project_verified:
        raise ValueError("unverified YouTube API projects must fail closed to private")

    title = _clean_text(options.title, "YouTube title", _MAX_TITLE_CHARS)
    category_id = _clean_category_id(options.category_id, verified=options.category_id_verified)
    if not isinstance(options.description, str):
        raise TypeError("YouTube description must be a string")
    description = options.description.strip()
    if len(description.encode("utf-8")) > _MAX_DESCRIPTION_BYTES:
        raise ValueError("YouTube description exceeds allowed size")

    token = _clean_token(access_token)
    query = urlencode({"uploadType": "resumable", "part": "snippet,status"})
    body = {
        "snippet": {"title": title, "description": description, "categoryId": category_id},
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": options.self_declared_made_for_kids,
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(request.asset.size_bytes),
        "X-Upload-Content-Type": request.asset.media_type,
    }
    return YouTubeInitRequest(url=f"{YOUTUBE_UPLOAD_INIT_URL}?{query}", headers=headers, json_body=body)


def build_upload_request(
    session_url: str,
    *,
    access_token: str,
    media_type: str,
    total_size: int,
    start_byte: int,
    end_byte: int,
    chunk_size: int,
) -> YouTubeUploadRequest:
    """Build one deterministic resumable PUT request contract without reading the asset."""

    url = _validate_session_url(session_url)
    token = _clean_token(access_token)
    if media_type not in _ALLOWED_VIDEO_MEDIA_TYPES:
        raise ValueError("unsupported YouTube video media type")
    _validate_total_size(total_size)
    for name, value in (("start_byte", start_byte), ("end_byte", end_byte), ("chunk_size", chunk_size)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
    if start_byte < 0 or end_byte < start_byte or end_byte >= total_size:
        raise ValueError("invalid YouTube resumable byte range")
    if chunk_size <= 0 or chunk_size % _RESUMABLE_CHUNK_GRANULARITY != 0:
        raise ValueError("YouTube resumable chunk size must be a positive multiple of 256 KB")
    if start_byte % chunk_size != 0:
        raise ValueError("YouTube resumable chunk start does not match the planned chunk size")

    content_length = end_byte - start_byte + 1
    is_final_chunk = end_byte == total_size - 1
    if is_final_chunk:
        if content_length > chunk_size:
            raise ValueError("final YouTube resumable chunk exceeds the planned chunk size")
    elif content_length != chunk_size:
        raise ValueError("non-final YouTube resumable chunks must use the planned chunk size")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": media_type,
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {start_byte}-{end_byte}/{total_size}",
    }
    return YouTubeUploadRequest(url=url, headers=headers, start_byte=start_byte, end_byte=end_byte)


def build_upload_status_probe(
    session_url: str,
    *,
    access_token: str,
    total_size: int,
) -> YouTubeUploadStatusProbe:
    """Build the official empty PUT used to reconcile an interrupted resumable upload."""

    url = _validate_session_url(session_url)
    token = _clean_token(access_token)
    size = _validate_total_size(total_size)
    return YouTubeUploadStatusProbe(
        url=url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Length": "0",
            "Content-Range": f"bytes */{size}",
        },
    )


def build_video_status_request(video_id: str, *, access_token: str) -> YouTubeStatusRequest:
    """Build a processing/status verification request after a confirmed video ID exists."""

    value = _clean_text(video_id, "YouTube video id", 128)
    if any(ch.isspace() for ch in value):
        raise ValueError("YouTube video id is malformed")
    token = _clean_token(access_token)
    query = urlencode({"part": "status,processingDetails", "id": value})
    return YouTubeStatusRequest(
        url=f"{YOUTUBE_VIDEO_STATUS_URL}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
