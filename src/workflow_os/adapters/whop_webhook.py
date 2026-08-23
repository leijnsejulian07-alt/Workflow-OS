from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

MAX_WEBHOOK_BODY_BYTES = 256 * 1024
MAX_HEADER_BYTES = 1024
MAX_EVENT_TYPE_CHARS = 128
MAX_CLOCK_SKEW_SECONDS = 300


@dataclass(frozen=True)
class VerifiedWhopWebhook:
    webhook_id: str
    webhook_timestamp: int
    event_id: str
    event_type: str
    api_version: str
    occurred_at: str
    account_id: str | None
    data: Mapping[str, object]
    payload_sha256: str


def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = ""
    for key, candidate in headers.items():
        if str(key).lower() == name:
            value = str(candidate).strip()
            break
    if not value:
        raise ValueError(f"missing {name} header")
    if len(value.encode("utf-8")) > MAX_HEADER_BYTES:
        raise ValueError(f"{name} header is too large")
    return value


def _utc_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _verify_signature(
    *,
    raw_body: bytes,
    webhook_id: str,
    webhook_timestamp: str,
    webhook_signature: str,
    secret: str,
) -> None:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Whop webhook secret is required")
    secret = secret.strip()
    if len(secret.encode("utf-8")) > MAX_HEADER_BYTES:
        raise ValueError("Whop webhook secret is too large")

    versions = [part.strip() for part in webhook_signature.split() if part.strip()]
    candidates: list[str] = []
    for part in versions:
        if part.startswith("v1,"):
            candidates.append(part[3:])
    if not candidates:
        raise ValueError("webhook signature has no supported v1 signature")

    signed = webhook_id.encode("utf-8") + b"." + webhook_timestamp.encode("ascii") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).digest()

    matched = False
    for candidate in candidates:
        try:
            supplied = base64.b64decode(candidate, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(supplied) == hashlib.sha256().digest_size and hmac.compare_digest(expected, supplied):
            matched = True
    if not matched:
        raise ValueError("invalid Whop webhook signature")


def verify_whop_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    *,
    secret: str,
    now: datetime | None = None,
) -> VerifiedWhopWebhook:
    """Verify one Whop Standard Webhooks request before parsing or using its data.

    Whop signs ``{webhook-id}.{webhook-timestamp}.{raw body}`` with HMAC-SHA256.
    The payload is parsed only after signature and replay-window validation succeed.
    No event produced here is cash evidence by itself; event-specific adapters must
    separately prove payout semantics before recording a receipt.
    """

    if not isinstance(raw_body, bytes):
        raise TypeError("raw_body must be bytes")
    if not isinstance(headers, Mapping):
        raise TypeError("headers must be a mapping")
    if not raw_body:
        raise ValueError("webhook body is empty")
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise ValueError("webhook body exceeds allowed size")

    webhook_id = _required_header(headers, "webhook-id")
    webhook_timestamp_raw = _required_header(headers, "webhook-timestamp")
    webhook_signature = _required_header(headers, "webhook-signature")

    try:
        webhook_timestamp = int(webhook_timestamp_raw)
    except ValueError as exc:
        raise ValueError("webhook timestamp must be an integer") from exc
    if webhook_timestamp < 0:
        raise ValueError("webhook timestamp must be non-negative")

    current = _utc_now(now)
    skew = abs(current.timestamp() - webhook_timestamp)
    if skew > MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("webhook timestamp is outside replay window")

    _verify_signature(
        raw_body=raw_body,
        webhook_id=webhook_id,
        webhook_timestamp=webhook_timestamp_raw,
        webhook_signature=webhook_signature,
        secret=secret,
    )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verified webhook body is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("verified webhook body must be a JSON object")

    event_id = payload.get("id")
    event_type = payload.get("type")
    api_version = payload.get("api_version")
    occurred_at = payload.get("timestamp")
    data = payload.get("data")

    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("webhook event id is required")
    if event_id != webhook_id:
        raise ValueError("body event id does not match webhook-id header")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("webhook event type is required")
    if len(event_type) > MAX_EVENT_TYPE_CHARS:
        raise ValueError("webhook event type is too long")
    if not isinstance(api_version, str) or not api_version.strip():
        raise ValueError("webhook api_version is required")
    if not isinstance(occurred_at, str) or not occurred_at.strip():
        raise ValueError("webhook timestamp field is required")
    try:
        parsed_occurred = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("webhook timestamp field is invalid") from exc
    if parsed_occurred.tzinfo is None:
        raise ValueError("webhook timestamp field must be timezone-aware")
    if not isinstance(data, dict):
        raise ValueError("webhook data must be an object")

    account = payload.get("account_id", payload.get("company_id"))
    if account is not None and (not isinstance(account, str) or not account.strip()):
        raise ValueError("webhook account identity is invalid")

    return VerifiedWhopWebhook(
        webhook_id=webhook_id,
        webhook_timestamp=webhook_timestamp,
        event_id=event_id,
        event_type=event_type,
        api_version=api_version,
        occurred_at=parsed_occurred.astimezone(timezone.utc).isoformat(),
        account_id=account,
        data=data,
        payload_sha256=hashlib.sha256(raw_body).hexdigest(),
    )
