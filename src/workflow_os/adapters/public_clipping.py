"""Fail-closed public campaign discovery for supported clipping marketplaces.

This module performs no network access or side effects. Reviewed transports may
supply bounded public campaign evidence from supported platforms. Public campaign
discovery never grants creator submission authority, payout authority, or zero-touch
execution.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from .contracts import AccessMode, DiscoveryRecord, SourcePolicy
from .reward_feed import normalize_reward_record

_EXECUTION_BLOCK_REASON = "official_creator_machine_submission_interface_not_verified"
_MAX_MONEY_CENTS = 100_000_000_000
_MAX_MINIMUM_VIEWS = 1_000_000_000

POLICIES = {
    "clipping_net": SourcePolicy(
        source_platform="clipping_net",
        allowed_hosts=frozenset({"clipping.net", "www.clipping.net"}),
        access_mode=AccessMode.PUBLIC_HTTP,
        max_response_bytes=1_048_576,
        max_redirects=2,
        requires_rights_evidence=True,
    ),
    "vues": SourcePolicy(
        source_platform="vues",
        allowed_hosts=frozenset({"vues.app", "www.vues.app"}),
        access_mode=AccessMode.PUBLIC_HTTP,
        max_response_bytes=1_048_576,
        max_redirects=2,
        requires_rights_evidence=True,
    ),
}

_MONEY_FIELDS = (
    "headline_budget",
    "remaining_budget",
    "cpm",
    "payout_per_1000_views",
)
_NONNEGATIVE_INTEGER_FIELDS = ("minimum_views",)


def _validate_optional_bounded_money(payload: Mapping[str, object], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric when present")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{key} must be finite and non-negative") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{key} must be finite and non-negative")
    try:
        quantized = amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"{key} is outside supported bounds") from exc
    if quantized != amount:
        raise ValueError(f"{key} may have at most two decimal places")
    cents = int(quantized * 100)
    if cents < 0 or cents > _MAX_MONEY_CENTS:
        raise ValueError(f"{key} is outside supported bounds")


def _validate_currency_binding(payload: Mapping[str, object]) -> None:
    currency = payload.get("currency")
    has_money = any(payload.get(key) is not None for key in _MONEY_FIELDS)
    if currency is None:
        if has_money:
            raise ValueError("money fields require explicit currency evidence")
        return
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise ValueError("currency must be a three-letter uppercase ASCII code")


def _validate_optional_nonnegative_integer(payload: Mapping[str, object], key: str) -> None:
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer when present")
    if value > _MAX_MINIMUM_VIEWS:
        raise ValueError(f"{key} is outside supported bounds")


def normalize_public_clipping_campaign(
    platform: str,
    payload: Mapping[str, object],
) -> DiscoveryRecord:
    """Normalize public clipping evidence without inventing execution capability."""
    if platform not in POLICIES:
        raise ValueError("unsupported public clipping platform")
    if not isinstance(payload, Mapping):
        raise ValueError("public clipping campaign payload must be a mapping")

    for key in _MONEY_FIELDS:
        _validate_optional_bounded_money(payload, key)
    _validate_currency_binding(payload)
    for key in _NONNEGATIVE_INTEGER_FIELDS:
        _validate_optional_nonnegative_integer(payload, key)

    normalized_payload = dict(payload)
    normalized_payload["machine_submission_verified"] = False
    normalized_payload["zero_touch_execution_enabled"] = False
    normalized_payload["execution_block_reason"] = _EXECUTION_BLOCK_REASON
    normalized_payload["payout_receipt_verified"] = False

    return normalize_reward_record(POLICIES[platform], normalized_payload)


def normalize_clipping_net_campaign(payload: Mapping[str, object]) -> DiscoveryRecord:
    return normalize_public_clipping_campaign("clipping_net", payload)


def normalize_vues_campaign(payload: Mapping[str, object]) -> DiscoveryRecord:
    return normalize_public_clipping_campaign("vues", payload)
