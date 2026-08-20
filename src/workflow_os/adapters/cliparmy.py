"""Thin Clip Army discovery adapter over the shared reward-feed boundary.

This module performs no network access or side effects. A reviewed transport may
supply already-bounded public/authorized evidence; unknown rights/payment facts
remain unknown for Opportunity Manager revalidation.
"""
from __future__ import annotations

from collections.abc import Mapping

from .contracts import AccessMode, DiscoveryRecord, SourcePolicy
from .reward_feed import normalize_reward_record

POLICY = SourcePolicy(
    source_platform="cliparmy",
    allowed_hosts=frozenset({"cliparmy.nl", "www.cliparmy.nl"}),
    access_mode=AccessMode.PUBLIC_HTTP,
    max_response_bytes=1_048_576,
    max_redirects=2,
    requires_rights_evidence=True,
)


def normalize_cliparmy_campaign(payload: Mapping[str, object]) -> DiscoveryRecord:
    """Normalize one bounded Clip Army campaign without inventing evidence."""
    return normalize_reward_record(POLICY, payload)
