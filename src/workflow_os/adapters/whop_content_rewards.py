"""Thin Whop Content Rewards discovery adapter over the shared reward-feed boundary.

This module performs no network access or side effects. A reviewed authorized
transport may supply already-bounded campaign evidence from Whop; unknown
rights/payment facts remain unknown for Opportunity Manager revalidation.
"""
from __future__ import annotations

from collections.abc import Mapping

from .contracts import AccessMode, DiscoveryRecord, SourcePolicy
from .reward_feed import normalize_reward_record

POLICY = SourcePolicy(
    source_platform="whop_content_rewards",
    allowed_hosts=frozenset({"whop.com", "www.whop.com"}),
    access_mode=AccessMode.AUTHORIZED_ACCOUNT,
    max_response_bytes=1_048_576,
    max_redirects=2,
    requires_rights_evidence=True,
)


def normalize_whop_content_reward(payload: Mapping[str, object]) -> DiscoveryRecord:
    """Normalize one bounded Whop Content Rewards campaign without inventing evidence."""
    return normalize_reward_record(POLICY, payload)
