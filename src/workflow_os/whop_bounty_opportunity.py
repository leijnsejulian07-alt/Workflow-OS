"""Fail-closed bridge from verified Whop workforce discovery into Opportunity Manager input.

Discovery capability is not opportunity approval. This module only creates a raw
Opportunity Manager payload when independent Workflow OS-owned rights, account,
worker, deliverable and economic evidence is explicit and internally consistent.
It performs no network access and no external side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .adapters.contracts import DiscoveryRecord


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "BLOCKED"})
_ALLOWED_DUPLICATE_STATES = frozenset({"CLEAR", "DUPLICATE", "CONFLICT"})
_ALLOWED_ATTENTION = frozenset({"NONE", "OWNER_APPROVAL", "KYC", "EXCEPTION", "EMERGENCY"})
_MAX_TEXT = 2048
_MAX_ACCOUNT_REQUIREMENTS = 64


@dataclass(frozen=True)
class TrustedWhopWorkforceEvidence:
    """Workflow OS-owned evidence required before opportunity admission."""

    rights_verified: bool
    account_authorized: bool
    worker_identity_verified: bool
    campaign_requirements_verified: bool
    deliverable_requirements_verified: bool
    usage_rights: str
    compliance_risk: str
    platform_risk: str
    duplicate_conflict_status: str
    user_attention_requirement: str
    expected_owner_minutes: float
    expected_revenue_eur: float
    expected_production_cost_eur: float
    expected_laptop_minutes: float
    estimated_success_probability: float
    probability_collection: float
    expected_time_to_cash_hours: float
    automation_completeness: float
    capital_required_eur: float
    remaining_budget_eur: float
    payout_cap_eur: float
    payout_formula: str
    payment_method: str
    approval_rules: str
    originality_requirements: str
    account_requirements: tuple[str, ...]
    deadline: str
    freshness_ttl_seconds: int
    evidence_sha256: str


def _text(value: str, name: str, *, max_len: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text) > max_len or any(ord(ch) < 32 and ch not in "\t\n" for ch in text):
        raise ValueError(f"{name} is missing or malformed")
    return text


def _finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _probability(value: float, name: str) -> float:
    result = _finite_nonnegative(value, name)
    if result > 1:
        raise ValueError(f"{name} must be within [0, 1]")
    return result


def _verified_discovery(record: DiscoveryRecord) -> None:
    if not isinstance(record, DiscoveryRecord):
        raise TypeError("record must be DiscoveryRecord")
    if record.source_platform != "whop_bounties":
        raise ValueError("discovery record is not a Whop Bounties record")
    fields = record.fields
    if fields.get("status") != "published":
        raise ValueError("Whop bounty is not published")
    if fields.get("bounty_type") != "workforce":
        raise ValueError("only workforce bounties have verified worker submission")
    if fields.get("machine_submission_verified") is not True:
        raise ValueError("Whop workforce machine submission is not verified")
    if fields.get("zero_touch_execution_enabled") is not True:
        raise ValueError("Whop workforce zero-touch capability is not enabled")
    if fields.get("execution_block_reason") not in (None, ""):
        raise ValueError("Whop workforce discovery is still execution-blocked")
    if not _SHA256_RE.fullmatch(record.raw_evidence_sha256):
        raise ValueError("discovery evidence digest is malformed")


def build_whop_workforce_opportunity(
    record: DiscoveryRecord,
    evidence: TrustedWhopWorkforceEvidence,
) -> dict[str, object]:
    """Create a raw Opportunity Manager payload from separately trusted evidence.

    Platform discovery fields are never allowed to assert rights, account authority,
    worker identity or economics. Those facts must arrive through ``evidence``.
    """
    _verified_discovery(record)
    if not isinstance(evidence, TrustedWhopWorkforceEvidence):
        raise TypeError("evidence must be TrustedWhopWorkforceEvidence")

    required_flags = (
        evidence.rights_verified,
        evidence.account_authorized,
        evidence.worker_identity_verified,
        evidence.campaign_requirements_verified,
        evidence.deliverable_requirements_verified,
    )
    if not all(flag is True for flag in required_flags):
        raise ValueError("Whop workforce opportunity evidence is incomplete")
    if not _SHA256_RE.fullmatch(evidence.evidence_sha256):
        raise ValueError("trusted opportunity evidence digest is malformed")

    usage_rights = _text(evidence.usage_rights, "usage_rights")
    payout_formula = _text(evidence.payout_formula, "payout_formula")
    payment_method = _text(evidence.payment_method, "payment_method")
    approval_rules = _text(evidence.approval_rules, "approval_rules")
    originality = _text(evidence.originality_requirements, "originality_requirements")
    deadline = _text(evidence.deadline, "deadline", max_len=128)

    compliance_risk = _text(evidence.compliance_risk, "compliance_risk", max_len=16).upper()
    platform_risk = _text(evidence.platform_risk, "platform_risk", max_len=16).upper()
    duplicate_state = _text(
        evidence.duplicate_conflict_status, "duplicate_conflict_status", max_len=16
    ).upper()
    attention = _text(
        evidence.user_attention_requirement, "user_attention_requirement", max_len=32
    ).upper()
    if compliance_risk not in _ALLOWED_RISKS or platform_risk not in _ALLOWED_RISKS:
        raise ValueError("risk evidence is invalid")
    if duplicate_state not in _ALLOWED_DUPLICATE_STATES:
        raise ValueError("duplicate/conflict evidence is invalid")
    if attention not in _ALLOWED_ATTENTION:
        raise ValueError("owner-attention evidence is invalid")

    owner_minutes = _finite_nonnegative(evidence.expected_owner_minutes, "expected_owner_minutes")
    if owner_minutes != 0:
        raise ValueError("recurring owner fulfillment is prohibited")

    expected_revenue = _finite_nonnegative(evidence.expected_revenue_eur, "expected_revenue_eur")
    production_cost = _finite_nonnegative(
        evidence.expected_production_cost_eur, "expected_production_cost_eur"
    )
    laptop_minutes = _finite_nonnegative(evidence.expected_laptop_minutes, "expected_laptop_minutes")
    success_probability = _probability(
        evidence.estimated_success_probability, "estimated_success_probability"
    )
    collection_probability = _probability(evidence.probability_collection, "probability_collection")
    time_to_cash = _finite_nonnegative(
        evidence.expected_time_to_cash_hours, "expected_time_to_cash_hours"
    )
    automation = _probability(evidence.automation_completeness, "automation_completeness")
    capital = _finite_nonnegative(evidence.capital_required_eur, "capital_required_eur")
    remaining_budget = _finite_nonnegative(evidence.remaining_budget_eur, "remaining_budget_eur")
    payout_cap = _finite_nonnegative(evidence.payout_cap_eur, "payout_cap_eur")

    if expected_revenue > payout_cap:
        raise ValueError("expected revenue exceeds independently verified payout cap")
    if expected_revenue > remaining_budget:
        raise ValueError("expected revenue exceeds independently verified remaining budget")

    if isinstance(evidence.freshness_ttl_seconds, bool) or not isinstance(
        evidence.freshness_ttl_seconds, int
    ):
        raise TypeError("freshness_ttl_seconds must be an integer")
    if evidence.freshness_ttl_seconds <= 0 or evidence.freshness_ttl_seconds > 86_400:
        raise ValueError("freshness_ttl_seconds must be within 1 second and 24 hours")

    requirements = evidence.account_requirements
    if not isinstance(requirements, tuple) or len(requirements) > _MAX_ACCOUNT_REQUIREMENTS:
        raise ValueError("account_requirements must be a bounded tuple")
    account_requirements = [
        _text(item, "account_requirement", max_len=512) for item in requirements
    ]

    return {
        "source_platform": record.source_platform,
        "campaign_id": record.campaign_id,
        "title": record.title,
        "category": "whop_workforce_bounty",
        "canonical_url": record.canonical_url,
        "source_evidence_sha256": record.raw_evidence_sha256,
        "opportunity_evidence_sha256": evidence.evidence_sha256,
        "bounty_type": "workforce",
        "machine_submission_verified": True,
        "zero_touch_execution_enabled": True,
        "rights_verification_state": "VERIFIED",
        "usage_rights": usage_rights,
        "account_authorized": True,
        "worker_identity_verified": True,
        "campaign_requirements_verified": True,
        "deliverable_requirements_verified": True,
        "compliance_risk": compliance_risk,
        "platform_risk": platform_risk,
        "duplicate_conflict_status": duplicate_state,
        "expected_owner_minutes": owner_minutes,
        "user_attention_requirement": attention,
        "source_checked_at": record.observed_at,
        "freshness_ttl_seconds": evidence.freshness_ttl_seconds,
        "deadline": deadline,
        "remaining_budget": remaining_budget,
        "payout_formula": payout_formula,
        "payout_cap": payout_cap,
        "payment_method": payment_method,
        "approval_rules": approval_rules,
        "originality_requirements": originality,
        "account_requirements": account_requirements,
        "expected_revenue": expected_revenue,
        "expected_production_cost": production_cost,
        "expected_laptop_minutes": laptop_minutes,
        "estimated_success_probability": success_probability,
        "probability_collection": collection_probability,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital,
        "allowed_countries": [],
        "platforms": ["whop"],
        "source_assets": [],
        "disclosure_requirements": [],
        "discovered_at": record.observed_at,
    }
