"""Fail-closed Clip Army public campaign discovery adapter.

This module performs no network access or side effects. A reviewed transport may
supply bounded evidence from Clip Army's public campaign surface. Public discovery
never implies creator submission authority: no official machine creator-submission
interface is verified here, so zero-touch execution is forced off.
"""
from __future__ import annotations

import math
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

_NUMERIC_FIELDS = (
    "headline_budget_eur",
    "remaining_budget",
    "cpm_eur",
    "payout_per_1000_views_eur",
)


def _validate_optional_nonnegative_number(payload: Mapping[str, object], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric when present")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{key} must be finite and non-negative")


def normalize_cliparmy_campaign(payload: Mapping[str, object]) -> DiscoveryRecord:
    """Normalize one public Clip Army campaign without inventing execution rights.

    Campaign-specific commercial facts and rights evidence are preserved only when
    explicitly supplied by reviewed evidence. Unknowns remain unknown. Remote input
    cannot grant creator-submission authority or claim a verified machine API.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Clip Army campaign payload must be a mapping")

    for key in _NUMERIC_FIELDS:
        _validate_optional_nonnegative_number(payload, key)

    normalized_payload = dict(payload)
    normalized_payload["machine_submission_verified"] = False
    normalized_payload["zero_touch_execution_enabled"] = False
    normalized_payload["execution_block_reason"] = (
        "official_creator_machine_submission_interface_not_verified"
    )

    return normalize_reward_record(POLICY, normalized_payload)
