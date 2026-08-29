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


@dataclass(frozen=True)
class YouTubeProjectEvidence:
    api_project_verified: bool
    owned_channel_verified: bool
    upload_scope_verified: bool


@dataclass(frozen=True)
class YouTubeUploadOptions:
    title: str
    description: str
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
        or not parsed.path.startswith("/upload/youtube/v3/videos")
    ):
        raise ValueError("YouTube resumable session URL has an unexpected origin")
    return session_url


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
    if not isinstance(options.description, str):
        raise TypeError("YouTube description must be a string")
    description = options.description.strip()
    if len(description.encode("utf-8")) > _MAX_DESCRIPTION_BYTES:
        raise ValueError("YouTube description exceeds allowed size")

    token = _clean_token(access_token)
    query = urlencode({"uploadType": "resumable", "part": "snippet,status"})
    body = {
        "snippet": {"title": title, "description": description},
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
) -> YouTubeUploadRequest:
    """Build one bounded resumable PUT request contract without reading the asset."""

    url = _validate_session_url(session_url)
    token = _clean_token(access_token)
    if media_type not in _ALLOWED_VIDEO_MEDIA_TYPES:
        raise ValueError("unsupported YouTube video media type")
    for name, value in (("total_size", total_size), ("start_byte", start_byte), ("end_byte", end_byte)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
    if total_size <= 0 or start_byte < 0 or end_byte < start_byte or end_byte >= total_size:
        raise ValueError("invalid YouTube resumable byte range")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": media_type,
        "Content-Length": str(end_byte - start_byte + 1),
        "Content-Range": f"bytes {start_byte}-{end_byte}/{total_size}",
    }
    return YouTubeUploadRequest(url=url, headers=headers, start_byte=start_byte, end_byte=end_byte)


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
