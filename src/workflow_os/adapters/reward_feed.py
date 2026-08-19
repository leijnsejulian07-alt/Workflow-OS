"""Dependency-free normalization for reward-platform discovery evidence.

This module performs no network access and no side effects. Platform-specific
adapters may feed already-bounded, authorized/public evidence into this layer.
Missing commercial or rights facts remain unknown; they are never inferred.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .contracts import DiscoveryRecord, SourcePolicy

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = ("campaign_id", "title", "canonical_url", "observed_at", "raw_evidence_sha256")


def normalize_reward_record(
    policy: SourcePolicy,
    payload: Mapping[str, object],
) -> DiscoveryRecord:
    """Validate minimal discovery evidence and preserve unknowns explicitly."""
    if not isinstance(payload, Mapping):
        raise ValueError("reward payload must be a mapping")

    values: dict[str, str] = {}
    for key in _REQUIRED:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        values[key] = value.strip()

    if not policy.allows_url(values["canonical_url"]):
        raise ValueError("canonical_url is outside source policy")
    if not _SHA256_RE.fullmatch(values["raw_evidence_sha256"]):
        raise ValueError("raw_evidence_sha256 must be lowercase SHA-256 hex")

    fields = {
        key: value
        for key, value in payload.items()
        if key not in _REQUIRED and key != "source_platform"
    }

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
