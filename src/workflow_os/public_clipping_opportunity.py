"""Fail-closed bridge from public clipping public discovery into Opportunity Manager input.

Public public clipping campaign discovery is useful for ranking opportunities, but it does
not prove creator submission authority. This bridge requires independent Workflow
OS-owned evidence for campaign rights and economics and always keeps execution
blocked until an official creator machine-submission interface is verified.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .adapters.contracts import DiscoveryRecord
from .opportunities import BLOCKED_CATEGORIES

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "BLOCKED"})
_ALLOWED_DUPLICATE_STATES = frozenset({"CLEAR", "DUPLICATE", "CONFLICT"})
_MAX_TEXT = 2048
_MAX_PLATFORMS = 16


@dataclass(frozen=True)
class TrustedPublicClippingCampaignEvidence:
    rights_verified: bool
    source_material_rights_verified: bool
    campaign_brief_verified: bool
    payout_terms_verified: bool
    allowed_platforms_verified: bool
    content_category: str
    usage_rights: str
    compliance_risk: str
    platform_risk: str
    duplicate_conflict_status: str
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
    allowed_platforms: tuple[str, ...]
    deadline: str
    freshness_ttl_seconds: int
    evidence_sha256: str
    economics_currency: str
    fx_provenance_verified: bool


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
    if record.source_platform not in {"clipping_net", "vues"}:
        raise ValueError("discovery record is not a public clipping record")
    if record.fields.get("machine_submission_verified") is not False:
        raise ValueError("public clipping public discovery must not assert machine submission")
    if record.fields.get("payout_receipt_verified") is not False:
        raise ValueError("public clipping discovery must not assert payout receipt verification")
    if record.fields.get("zero_touch_execution_enabled") is not False:
        raise ValueError("public clipping public discovery must keep zero-touch execution disabled")
    if record.fields.get("execution_block_reason") != "official_creator_machine_submission_interface_not_verified":
        raise ValueError("public clipping execution block reason is missing or inconsistent")
    if not _SHA256_RE.fullmatch(record.raw_evidence_sha256):
        raise ValueError("discovery evidence digest is malformed")


def build_public_clipping_opportunity(
    record: DiscoveryRecord,
    evidence: TrustedPublicClippingCampaignEvidence,
) -> dict[str, object]:
    """Create a central Opportunity Manager payload without granting execution authority."""
    _verified_discovery(record)
    if not isinstance(evidence, TrustedPublicClippingCampaignEvidence):
        raise TypeError("evidence must be TrustedPublicClippingCampaignEvidence")

    required_flags = (
        evidence.rights_verified,
        evidence.source_material_rights_verified,
        evidence.campaign_brief_verified,
        evidence.payout_terms_verified,
        evidence.allowed_platforms_verified,
    )
    if not all(flag is True for flag in required_flags):
        raise ValueError("public clipping campaign evidence is incomplete")
    if not _SHA256_RE.fullmatch(evidence.evidence_sha256):
        raise ValueError("trusted campaign evidence digest is malformed")
    currency = _text(evidence.economics_currency, "economics_currency", max_len=3)
    if currency != "EUR":
        raise ValueError("Opportunity Manager economics must be independently evidenced in EUR")
    if record.source_platform == "vues" and evidence.fx_provenance_verified is not True:
        raise ValueError("Vues USD discovery requires independently verified EUR/FX provenance")

    category = _text(evidence.content_category, "content_category", max_len=64).lower()
    if category in BLOCKED_CATEGORIES:
        raise ValueError("prohibited opportunity category")

    compliance_risk = _text(evidence.compliance_risk, "compliance_risk", max_len=16).upper()
    platform_risk = _text(evidence.platform_risk, "platform_risk", max_len=16).upper()
    duplicate_state = _text(
        evidence.duplicate_conflict_status, "duplicate_conflict_status", max_len=16
    ).upper()
    if compliance_risk not in _ALLOWED_RISKS or platform_risk not in _ALLOWED_RISKS:
        raise ValueError("risk evidence is invalid")
    if duplicate_state not in _ALLOWED_DUPLICATE_STATES:
        raise ValueError("duplicate/conflict evidence is invalid")

    expected_revenue = _finite_nonnegative(evidence.expected_revenue_eur, "expected_revenue_eur")
    production_cost = _finite_nonnegative(
        evidence.expected_production_cost_eur, "expected_production_cost_eur"
    )
    laptop_minutes = _finite_nonnegative(evidence.expected_laptop_minutes, "expected_laptop_minutes")
    success_probability = _probability(
        evidence.estimated_success_probability, "estimated_success_probability"
    )
    collection_probability = _probability(evidence.probability_collection, "probability_collection")
    time_to_cash = _finite_nonnegative(evidence.expected_time_to_cash_hours, "expected_time_to_cash_hours")
    automation = _probability(evidence.automation_completeness, "automation_completeness")
    capital = _finite_nonnegative(evidence.capital_required_eur, "capital_required_eur")
    remaining_budget = _finite_nonnegative(evidence.remaining_budget_eur, "remaining_budget_eur")
    payout_cap = _finite_nonnegative(evidence.payout_cap_eur, "payout_cap_eur")
    if expected_revenue > payout_cap:
        raise ValueError("expected revenue exceeds independently verified payout cap")
    if expected_revenue > remaining_budget:
        raise ValueError("expected revenue exceeds independently verified remaining budget")

    if isinstance(evidence.freshness_ttl_seconds, bool) or not isinstance(evidence.freshness_ttl_seconds, int):
        raise TypeError("freshness_ttl_seconds must be an integer")
    if evidence.freshness_ttl_seconds <= 0 or evidence.freshness_ttl_seconds > 86_400:
        raise ValueError("freshness_ttl_seconds must be within 1 second and 24 hours")

    if not isinstance(evidence.allowed_platforms, tuple) or not evidence.allowed_platforms:
        raise ValueError("allowed_platforms must be a non-empty tuple")
    if len(evidence.allowed_platforms) > _MAX_PLATFORMS:
        raise ValueError("too many allowed platforms")
    allowed_platforms = [_text(item, "allowed_platform", max_len=64).lower() for item in evidence.allowed_platforms]

    return {
        "source_platform": record.source_platform,
        "campaign_id": record.campaign_id,
        "title": record.title,
        "category": category,
        "canonical_url": record.canonical_url,
        "source_evidence_sha256": record.raw_evidence_sha256,
        "opportunity_evidence_sha256": evidence.evidence_sha256,
        "machine_submission_verified": False,
        "zero_touch_execution_enabled": False,
        "execution_block_reason": "official_creator_machine_submission_interface_not_verified",
        "rights_verification_state": "VERIFIED",
        "usage_rights": _text(evidence.usage_rights, "usage_rights"),
        "source_material_rights_verified": True,
        "campaign_brief_verified": True,
        "payout_terms_verified": True,
        "allowed_platforms_verified": True,
        "compliance_risk": compliance_risk,
        "platform_risk": platform_risk,
        "duplicate_conflict_status": duplicate_state,
        "expected_owner_minutes": 0.0,
        "user_attention_requirement": "EXCEPTION",
        "source_checked_at": record.observed_at,
        "freshness_ttl_seconds": evidence.freshness_ttl_seconds,
        "deadline": _text(evidence.deadline, "deadline", max_len=128),
        "remaining_budget": remaining_budget,
        "payout_formula": _text(evidence.payout_formula, "payout_formula"),
        "payout_cap": payout_cap,
        "payment_method": _text(evidence.payment_method, "payment_method"),
        "approval_rules": _text(evidence.approval_rules, "approval_rules"),
        "originality_requirements": _text(evidence.originality_requirements, "originality_requirements"),
        "account_requirements": [],
        "expected_revenue": expected_revenue,
        "expected_production_cost": production_cost,
        "expected_laptop_minutes": laptop_minutes,
        "estimated_success_probability": success_probability,
        "probability_collection": collection_probability,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital,
        "allowed_countries": [],
        "platforms": allowed_platforms,
        "source_assets": [],
        "disclosure_requirements": [],
        "discovered_at": record.observed_at,
    }




