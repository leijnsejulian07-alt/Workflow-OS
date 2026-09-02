from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"https"}
_ALLOWED_MEDIA_TYPES = {"video/mp4", "video/webm", "image/png", "image/jpeg"}
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TEXT = 5000


@dataclass(frozen=True)
class SubmissionAsset:
    path: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class SubmissionRequest:
    opportunity_id: str
    source_platform: str
    campaign_url: str
    destination_url: str
    caption: str
    asset: SubmissionAsset
    rights_verified: bool
    account_authorized: bool
    disclosure_satisfied: bool
    campaign_requirements_verified: bool
    account_identity: str = ""


@dataclass(frozen=True)
class SubmissionDecision:
    allowed: bool
    reason: str
    idempotency_key: str | None


def _clean_text(value: str, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} must be 1..{maximum} characters")
    return cleaned


def _validate_https_url(value: str, field: str) -> str:
    value = _clean_text(value, field, maximum=2000)
    parsed = urlparse(value)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not contain userinfo")
    return value


def _validate_asset(asset: SubmissionAsset) -> SubmissionAsset:
    if not isinstance(asset, SubmissionAsset):
        raise ValueError("asset must be SubmissionAsset")
    path = _clean_text(asset.path, "asset.path", maximum=500)
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("asset.path must be a relative traversal-free path")
    if asset.media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("asset.media_type is not allowed")
    if not isinstance(asset.size_bytes, int) or isinstance(asset.size_bytes, bool):
        raise ValueError("asset.size_bytes must be an integer")
    if not 1 <= asset.size_bytes <= _MAX_ASSET_BYTES:
        raise ValueError("asset.size_bytes is outside allowed bounds")
    digest = _clean_text(asset.sha256, "asset.sha256", maximum=64).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("asset.sha256 must be a SHA-256 hex digest")
    return SubmissionAsset(path=path, media_type=asset.media_type, size_bytes=asset.size_bytes, sha256=digest)


def evaluate_submission(request: SubmissionRequest, *, allowed_destination_hosts: Iterable[str]) -> SubmissionDecision:
    """Fail-closed gate before any external publication/submission side effect.

    This function never performs network or platform actions. It only proves that
    the minimum evidence required for a later official adapter call is present.
    """

    if not isinstance(request, SubmissionRequest):
        return SubmissionDecision(False, "invalid request type", None)

    try:
        opportunity_id = _clean_text(request.opportunity_id, "opportunity_id", maximum=200)
        source_platform = _clean_text(request.source_platform, "source_platform", maximum=100)
        campaign_url = _validate_https_url(request.campaign_url, "campaign_url")
        destination_url = _validate_https_url(request.destination_url, "destination_url")
        caption = request.caption if isinstance(request.caption, str) else ""
        if len(caption) > _MAX_TEXT:
            raise ValueError("caption exceeds 5000 characters")
        asset = _validate_asset(request.asset)
        account_identity = ""
        if request.account_identity:
            account_identity = _clean_text(request.account_identity, "account_identity", maximum=256)
    except ValueError as exc:
        return SubmissionDecision(False, str(exc), None)

    allowed_hosts = {str(host).strip().lower().rstrip(".") for host in allowed_destination_hosts if str(host).strip()}
    destination_host = (urlparse(destination_url).hostname or "").lower().rstrip(".")
    if destination_host not in allowed_hosts:
        return SubmissionDecision(False, "destination host is not explicitly allowed", None)

    evidence = (
        (request.rights_verified, "rights evidence is not verified"),
        (request.account_authorized, "account is not authorized for submission"),
        (request.disclosure_satisfied, "required disclosure is not satisfied"),
        (request.campaign_requirements_verified, "campaign requirements are not verified"),
    )
    for condition, reason in evidence:
        if condition is not True:
            return SubmissionDecision(False, reason, None)

    canonical = "\n".join(
        [
            opportunity_id,
            source_platform,
            campaign_url,
            destination_url,
            caption,
            asset.path,
            asset.media_type,
            str(asset.size_bytes),
            asset.sha256,
        ]
    ).encode("utf-8")
    if account_identity:
        canonical += b"\naccount:" + account_identity.encode("utf-8")
    key = f"submit:{hashlib.sha256(canonical).hexdigest()}"
    return SubmissionDecision(True, "submission evidence verified", key)
