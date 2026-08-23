from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse
import re


WHOP_BOUNTY_SUBMISSION_URL = "https://api.whop.com/api/v1/bounty_submissions"
WHOP_API_VERSION_DATE = "2026-08-21"

_BOUNTY_ID_RE = re.compile(r"^bnty_[A-Za-z0-9_-]{3,200}$")
_SUBMISSION_ID_RE = re.compile(r"^btys_[A-Za-z0-9_-]{3,200}$")
_FILE_ID_RE = re.compile(r"^file_[A-Za-z0-9_-]{3,200}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,255}$")
_ALLOWED_DELIVERABLE_TYPES = frozenset({"content_url", "media"})
_MAX_URLS = 8
_MAX_FILES = 8
_MAX_CAPTION = 4000


@dataclass(frozen=True)
class WhopBountySubmissionEvidence:
    """Workflow OS-owned evidence required before authoring a worker submission."""

    user_credential_verified: bool
    worker_identity_verified: bool
    rights_verified: bool
    campaign_requirements_verified: bool
    deliverable_verified: bool


@dataclass(frozen=True)
class WhopBountyDeliverable:
    deliverable_type: str
    urls: tuple[str, ...] = ()
    file_ids: tuple[str, ...] = ()
    caption: str = ""


@dataclass(frozen=True)
class WhopBountySubmissionRequest:
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]


@dataclass(frozen=True)
class WhopBountySubmissionResult:
    submission_id: str
    bounty_id: str
    status: str


def _bounded_token(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("Whop user token must be a string")
    value = token.strip()
    if not value or len(value) > 8192 or any(ch in "\r\n" for ch in value):
        raise ValueError("Whop user token is missing or malformed")
    return value


def _validate_idempotency_key(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("idempotency key must be a string")
    key = value.strip()
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise ValueError("idempotency key is malformed")
    return key


def _validate_https_url(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("deliverable URL must be a string")
    url = value.strip()
    if not url or len(url) > 2048:
        raise ValueError("deliverable URL is missing or too long")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or not parsed.path
    ):
        raise ValueError("deliverable URL must use a normal HTTPS origin")
    return url


def _validate_deliverable(deliverable: WhopBountyDeliverable) -> dict[str, object]:
    if not isinstance(deliverable, WhopBountyDeliverable):
        raise TypeError("deliverable must be WhopBountyDeliverable")
    dtype = deliverable.deliverable_type.strip().lower() if isinstance(deliverable.deliverable_type, str) else ""
    if dtype not in _ALLOWED_DELIVERABLE_TYPES:
        raise ValueError("unsupported Whop bounty deliverable type")
    if len(deliverable.urls) > _MAX_URLS or len(deliverable.file_ids) > _MAX_FILES:
        raise ValueError("Whop bounty deliverable exceeds item limits")

    urls = tuple(_validate_https_url(item) for item in deliverable.urls)
    if len(set(urls)) != len(urls):
        raise ValueError("duplicate deliverable URLs are not allowed")

    file_ids: list[str] = []
    for item in deliverable.file_ids:
        if not isinstance(item, str) or not _FILE_ID_RE.fullmatch(item.strip()):
            raise ValueError("Whop file id is malformed")
        file_ids.append(item.strip())
    if len(set(file_ids)) != len(file_ids):
        raise ValueError("duplicate Whop file ids are not allowed")

    if not urls and not file_ids:
        raise ValueError("Whop workforce submission requires at least one URL or file")

    caption = deliverable.caption.strip() if isinstance(deliverable.caption, str) else ""
    if len(caption) > _MAX_CAPTION or any(ord(ch) < 32 and ch not in "\t\n" for ch in caption):
        raise ValueError("Whop bounty caption is invalid")

    body: dict[str, object] = {"type": dtype}
    if urls:
        body["urls"] = list(urls)
    if file_ids:
        body["file_ids"] = file_ids
    if caption:
        body["caption"] = caption
    return body


def build_workforce_submission_request(
    *,
    bounty_id: str,
    deliverable: WhopBountyDeliverable,
    evidence: WhopBountySubmissionEvidence,
    user_token: str,
    idempotency_key: str,
) -> WhopBountySubmissionRequest:
    """Build Whop's documented one-shot workforce submission request without I/O.

    Whop documents that worker submissions require a user credential; account API
    keys cannot author submissions. Workflow OS therefore requires explicit
    user-credential evidence and never infers worker authority from possession of
    an arbitrary bearer token.
    """
    if not isinstance(evidence, WhopBountySubmissionEvidence):
        raise TypeError("evidence must be WhopBountySubmissionEvidence")
    required = (
        evidence.user_credential_verified,
        evidence.worker_identity_verified,
        evidence.rights_verified,
        evidence.campaign_requirements_verified,
        evidence.deliverable_verified,
    )
    if not all(flag is True for flag in required):
        raise ValueError("Whop bounty submission evidence is incomplete")

    if not isinstance(bounty_id, str) or not _BOUNTY_ID_RE.fullmatch(bounty_id.strip()):
        raise ValueError("Whop bounty id is malformed")
    token = _bounded_token(user_token)
    idem = _validate_idempotency_key(idempotency_key)
    deliverable_body = _validate_deliverable(deliverable)

    return WhopBountySubmissionRequest(
        url=WHOP_BOUNTY_SUBMISSION_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Api-Version-Date": WHOP_API_VERSION_DATE,
            "Idempotency-Key": idem,
        },
        json_body={"bounty_id": bounty_id.strip(), "deliverable": deliverable_body},
    )


def parse_workforce_submission_response(
    *,
    status_code: int,
    payload: Mapping[str, object],
    expected_bounty_id: str,
) -> WhopBountySubmissionResult:
    """Normalize only a confirmed Whop submission creation response."""
    if status_code != 201:
        raise ValueError("Whop bounty submission was not confirmed as created")
    if not isinstance(payload, Mapping):
        raise TypeError("Whop bounty submission response must be a mapping")
    if not isinstance(expected_bounty_id, str) or not _BOUNTY_ID_RE.fullmatch(expected_bounty_id.strip()):
        raise ValueError("expected Whop bounty id is malformed")

    submission_id = payload.get("id")
    bounty_id = payload.get("bounty_id")
    status = payload.get("status")
    if not isinstance(submission_id, str) or not _SUBMISSION_ID_RE.fullmatch(submission_id.strip()):
        raise ValueError("Whop bounty submission response lacks a valid submission id")
    if bounty_id != expected_bounty_id.strip():
        raise ValueError("Whop bounty submission response changed bounty identity")
    if status != "submitted":
        raise ValueError("Whop bounty submission response is not in submitted state")

    return WhopBountySubmissionResult(
        submission_id=submission_id.strip(),
        bounty_id=expected_bounty_id.strip(),
        status="submitted",
    )
