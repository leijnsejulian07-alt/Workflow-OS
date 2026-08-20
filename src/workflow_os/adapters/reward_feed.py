"""Dependency-free normalization for reward-platform discovery evidence.

This module performs no network access and no side effects. Platform-specific
adapters may feed already-bounded, authorized/public evidence into this layer.
Missing commercial or rights facts remain unknown; they are never inferred.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from .contracts import DiscoveryRecord, SourcePolicy

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = ("campaign_id", "title", "canonical_url", "observed_at", "raw_evidence_sha256")
_MAX_ID_LENGTH = 256
_MAX_TITLE_LENGTH = 1_024
_MAX_FIELD_COUNT = 64
_MAX_FIELD_KEY_LENGTH = 128
_MAX_STRING_LENGTH = 8_192
_MAX_SEQUENCE_ITEMS = 64
_MAX_NESTING_DEPTH = 3
_MAX_FUTURE_SKEW = timedelta(minutes=5)


def _parse_observed_at(value: str) -> datetime:
    candidate = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    observed = parsed.astimezone(timezone.utc)
    if observed > datetime.now(timezone.utc) + _MAX_FUTURE_SKEW:
        raise ValueError("observed_at is implausibly future-dated")
    return observed


def _bounded_field_value(value: object, *, depth: int = 0) -> object:
    if depth > _MAX_NESTING_DEPTH:
        raise ValueError("reward field nesting exceeds limit")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise ValueError("reward field string exceeds limit")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_FIELD_COUNT:
            raise ValueError("reward field mapping exceeds limit")
        result: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key or len(key) > _MAX_FIELD_KEY_LENGTH:
                raise ValueError("reward field mapping key is invalid")
            result[key] = _bounded_field_value(nested, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_SEQUENCE_ITEMS:
            raise ValueError("reward field sequence exceeds limit")
        return [_bounded_field_value(item, depth=depth + 1) for item in value]
    raise ValueError("reward field contains unsupported value type")


def normalize_reward_record(
    policy: SourcePolicy,
    payload: Mapping[str, object],
) -> DiscoveryRecord:
    """Validate bounded discovery evidence and preserve unknowns explicitly."""
    if not isinstance(payload, Mapping):
        raise ValueError("reward payload must be a mapping")
    if len(payload) > _MAX_FIELD_COUNT + len(_REQUIRED) + 1:
        raise ValueError("reward payload contains too many fields")

    values: dict[str, str] = {}
    for key in _REQUIRED:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        values[key] = value.strip()

    if len(values["campaign_id"]) > _MAX_ID_LENGTH:
        raise ValueError("campaign_id exceeds limit")
    if len(values["title"]) > _MAX_TITLE_LENGTH:
        raise ValueError("title exceeds limit")
    if not policy.allows_url(values["canonical_url"]):
        raise ValueError("canonical_url is outside source policy")
    if not _SHA256_RE.fullmatch(values["raw_evidence_sha256"]):
        raise ValueError("raw_evidence_sha256 must be lowercase SHA-256 hex")
    _parse_observed_at(values["observed_at"])

    fields: dict[str, object] = {}
    for key, value in payload.items():
        if key in _REQUIRED or key == "source_platform":
            continue
        if not isinstance(key, str) or not key or len(key) > _MAX_FIELD_KEY_LENGTH:
            raise ValueError("reward field key is invalid")
        fields[key] = _bounded_field_value(value)

    # Do not let remote payloads impersonate another configured source.
    supplied_source = payload.get("source_platform")
    if supplied_source is not None and supplied_source != policy.source_platform:
        raise ValueError("source_platform does not match configured policy")

    return DiscoveryRecord(
        source_platform=policy.source_platform,
        campaign_id=values["campaign_id"],
        title=values["title"],
        canonical_url=values["canonical_url"],
        observed_at=values["observed_at"],
        raw_evidence_sha256=values["raw_evidence_sha256"],
        fields=fields,
    )
