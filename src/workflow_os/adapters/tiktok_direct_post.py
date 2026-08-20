from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from workflow_os.submissions import SubmissionRequest


TIKTOK_API_HOST = "open.tiktokapis.com"
TIKTOK_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_ALLOWED_PRIVACY_LEVELS = frozenset(
    {
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "FOLLOWER_OF_CREATOR",
        "SELF_ONLY",
    }
)
_ALLOWED_VIDEO_MEDIA_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})


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


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _validate_access_token(access_token: str) -> str:
    if not isinstance(access_token, str):
        raise TypeError("TikTok access token must be a string")
    token = access_token.strip()
    if not token or len(token) > 4096 or any(ch.isspace() for ch in token):
        raise ValueError("TikTok access token is missing or malformed")
    return token


def build_video_init_request(
    request: SubmissionRequest,
    *,
    options: TikTokDirectPostOptions,
    access_token: str,
) -> TikTokInitRequest:
    """Build the official Direct Post video-init request without performing I/O.

    Workflow OS must run the central submission gate before this adapter. This
    adapter additionally enforces TikTok-specific creator-info, consent, privacy,
    media and caption constraints. Secrets are accepted only at call time and are
    not retained in any returned payload other than the required Authorization
    header that must be handed directly to a bounded HTTP transport.
    """

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
    if request.asset.size_bytes <= 0:
        raise ValueError("TikTok video size must be positive")
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
    body = {
        "post_info": {
            "title": request.caption,
            "privacy_level": privacy,
            "is_aigc": bool(options.is_aigc),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": request.asset.size_bytes,
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

    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not isinstance(publish_id, str) or not publish_id.strip() or len(publish_id) > 512:
        raise ValueError("TikTok init response is missing a bounded publish_id")
    if not isinstance(upload_url, str) or not upload_url.startswith("https://open-upload.tiktokapis.com/"):
        raise ValueError("TikTok init response returned an unexpected upload host")
    if len(upload_url) > 8192:
        raise ValueError("TikTok upload URL is too long")

    return TikTokInitResult(publish_id=publish_id.strip(), upload_url=upload_url)
