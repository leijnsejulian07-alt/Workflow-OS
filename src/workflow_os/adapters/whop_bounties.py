"""Fail-closed Whop Bounties discovery adapter.

This module normalizes bounded responses from Whop's documented Bounties API.
It performs no network access and grants no per-opportunity submission authority.
The official machine-submission surface is recorded only for workforce bounties;
zero-touch execution remains disabled here until the durable worker path binds the
exact discovered opportunity to its submission side effect.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping

from .contracts import AccessMode, DiscoveryRecord, SourcePolicy
from .reward_feed import normalize_reward_record

POLICY = SourcePolicy(
    source_platform="whop_bounties",
    allowed_hosts=frozenset({"api.whop.com", "sandbox-api.whop.com"}),
    access_mode=AccessMode.OFFICIAL_API,
    max_response_bytes=1_048_576,
    max_redirects=0,
    requires_rights_evidence=True,
)

_BOUNTY_ID_RE = re.compile(r"^bnty_[A-Za-z0-9_\-]{3,200}$")
_CURRENCY_RE = re.compile(r"^[a-z0-9]{3,8}$")
_ALLOWED_STATUSES = frozenset({"published", "archived"})
_ALLOWED_TYPES = frozenset({"classic", "user_funded", "workforce"})


def _required_string(payload: Mapping[str, object], key: str, *, max_len: int = 8192) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    value = value.strip()
    if len(value) > max_len:
        raise ValueError(f"{key} exceeds limit")
    return value


def _nonnegative_number(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{key} must be finite and non-negative")
    return number


def normalize_whop_bounty(
    payload: Mapping[str, object],
    *,
    observed_at: str,
    raw_evidence_sha256: str,
    api_host: str = "api.whop.com",
) -> DiscoveryRecord:
    """Normalize one official Whop bounty without inventing execution authority.

    Whop's reviewed worker submission contract applies only to ``workforce``
    bounties. Discovery may record that platform capability, but this adapter does
    not decide rights, worker identity, deliverable validity, account authority or
    durable execution readiness. Those remain separate fail-closed gates.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("bounty payload must be a mapping")
    if api_host not in POLICY.allowed_hosts:
        raise ValueError("api_host is outside Whop Bounties source policy")

    bounty_id = _required_string(payload, "id", max_len=256)
    if not _BOUNTY_ID_RE.fullmatch(bounty_id):
        raise ValueError("bounty id is invalid")

    title = _required_string(payload, "title", max_len=1024)
    description = _required_string(payload, "description")
    status = _required_string(payload, "status", max_len=32).lower()
    if status not in _ALLOWED_STATUSES:
        raise ValueError("bounty status is unsupported")

    bounty_type = _required_string(payload, "bounty_type", max_len=32).lower()
    if bounty_type not in _ALLOWED_TYPES:
        raise ValueError("bounty type is unsupported")

    currency = _required_string(payload, "currency", max_len=8).lower()
    if not _CURRENCY_RE.fullmatch(currency):
        raise ValueError("currency is invalid")

    total_available = _nonnegative_number(payload, "total_available")
    total_paid = _nonnegative_number(payload, "total_paid")

    vote_threshold = payload.get("vote_threshold")
    if isinstance(vote_threshold, bool) or not isinstance(vote_threshold, int) or vote_threshold < 0:
        raise ValueError("vote_threshold must be a non-negative integer")

    created_at = _required_string(payload, "created_at", max_len=128)
    updated_at = _required_string(payload, "updated_at", max_len=128)

    machine_submission_verified = bounty_type == "workforce"
    if machine_submission_verified:
        execution_block_reason = "durable_opportunity_submission_binding_not_verified"
    else:
        execution_block_reason = "official_worker_submission_requires_workforce_bounty"

    normalized_payload: dict[str, object] = {
        "campaign_id": bounty_id,
        "title": title,
        "canonical_url": f"https://{api_host}/api/v1/bounties/{bounty_id}",
        "observed_at": observed_at,
        "raw_evidence_sha256": raw_evidence_sha256,
        "description": description,
        "status": status,
        "total_available": total_available,
        "total_paid": total_paid,
        "currency": currency,
        "bounty_type": bounty_type,
        "vote_threshold": vote_threshold,
        "created_at": created_at,
        "updated_at": updated_at,
        "machine_submission_verified": machine_submission_verified,
        "zero_touch_execution_enabled": False,
        "execution_block_reason": execution_block_reason,
    }
    return normalize_reward_record(POLICY, normalized_payload)
