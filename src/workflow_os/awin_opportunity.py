"""Evidence-bound bridge from Awin program terms into the shared Opportunity Manager."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import re

from .opportunities import BLOCKED_CATEGORIES

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MODELS = frozenset({"CPA", "CPL", "CPC"})
_ALLOWED_CHANNELS = frozenset({"CONTENT", "DISPLAY", "SEARCH"})
_ALLOWED_RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "BLOCKED"})
_ALLOWED_DUPLICATE_STATES = frozenset({"CLEAR", "DUPLICATE", "CONFLICT"})
_MAX_TEXT = 2048


@dataclass(frozen=True)
class TrustedAwinProgramEvidence:
    publisher_id: int
    advertiser_id: int
    program_name: str
    program_approved: bool
    terms_verified: bool
    promotional_channel: str
    promotional_channel_approved: bool
    content_category: str
    usage_rights: str
    disclosure_requirements: tuple[str, ...]
    commission_model: str
    commission_rate: float
    commission_rate_is_percent: bool
    average_order_value_eur: float
    expected_clicks: float
    expected_conversion_rate: float
    expected_approval_rate: float
    expected_production_cost_eur: float
    expected_laptop_minutes: float
    expected_time_to_cash_hours: float
    automation_completeness: float
    capital_required_eur: float
    compliance_risk: str
    platform_risk: str
    duplicate_conflict_status: str
    cookie_window_days: int
    payment_method: str
    approval_rules: str
    originality_requirements: str
    observed_at: str
    deadline: str
    freshness_ttl_seconds: int
    evidence_sha256: str


def _text(value: object, name: str, *, max_len: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 and ch not in "\t\n" for ch in cleaned):
        raise ValueError(f"{name} is missing or malformed")
    return cleaned


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _probability(value: object, name: str) -> float:
    result = _nonnegative(value, name)
    if result > 1:
        raise ValueError(f"{name} must be within [0, 1]")
    return result


def _timestamp(value: object, name: str) -> str:
    text = _text(value, name, max_len=128)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware ISO-8601")
    return parsed.astimezone(timezone.utc).isoformat()


def _digest(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip()):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    return value.strip()


def _opportunity_id(evidence: TrustedAwinProgramEvidence) -> str:
    material = f"awin|{evidence.publisher_id}|{evidence.advertiser_id}|{evidence.promotional_channel.upper()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_awin_opportunity(evidence: TrustedAwinProgramEvidence) -> dict[str, object]:
    """Return a central Opportunity Manager payload from independently verified Awin terms."""
    if not isinstance(evidence, TrustedAwinProgramEvidence):
        raise TypeError("evidence must be TrustedAwinProgramEvidence")
    publisher_id = _positive_int(evidence.publisher_id, "publisher_id")
    advertiser_id = _positive_int(evidence.advertiser_id, "advertiser_id")
    if evidence.program_approved is not True:
        raise ValueError("Awin program is not approved for this publisher")
    if evidence.terms_verified is not True:
        raise ValueError("Awin program terms are not independently verified")
    if evidence.promotional_channel_approved is not True:
        raise ValueError("promotional channel is not approved by program terms")

    program_name = _text(evidence.program_name, "program_name", max_len=256)
    channel = _text(evidence.promotional_channel, "promotional_channel", max_len=32).upper()
    if channel not in _ALLOWED_CHANNELS:
        raise ValueError("unsupported or high-risk Awin promotional channel")
    category = _text(evidence.content_category, "content_category", max_len=64).lower()
    if category in BLOCKED_CATEGORIES:
        raise ValueError("prohibited opportunity category")

    model = _text(evidence.commission_model, "commission_model", max_len=16).upper()
    if model not in _ALLOWED_MODELS:
        raise ValueError("unsupported Awin commission model")
    rate = _nonnegative(evidence.commission_rate, "commission_rate")
    if evidence.commission_rate_is_percent is True:
        if rate > 100:
            raise ValueError("percentage commission rate exceeds 100%")
    elif evidence.commission_rate_is_percent is False:
        if model == "CPC":
            pass
    else:
        raise TypeError("commission_rate_is_percent must be boolean")

    clicks = _nonnegative(evidence.expected_clicks, "expected_clicks")
    conversion = _probability(evidence.expected_conversion_rate, "expected_conversion_rate")
    approval = _probability(evidence.expected_approval_rate, "expected_approval_rate")
    average_order = _nonnegative(evidence.average_order_value_eur, "average_order_value_eur")
    production_cost = _nonnegative(evidence.expected_production_cost_eur, "expected_production_cost_eur")
    laptop_minutes = _nonnegative(evidence.expected_laptop_minutes, "expected_laptop_minutes")
    time_to_cash = _nonnegative(evidence.expected_time_to_cash_hours, "expected_time_to_cash_hours")
    automation = _probability(evidence.automation_completeness, "automation_completeness")
    capital = _nonnegative(evidence.capital_required_eur, "capital_required_eur")

    if evidence.commission_rate_is_percent:
        if model != "CPA":
            raise ValueError("percentage commission is supported only for CPA in v1")
        gross = clicks * conversion * average_order * (rate / 100.0)
    elif model == "CPA" or model == "CPL":
        gross = clicks * conversion * rate
    else:
        gross = clicks * rate

    compliance_risk = _text(evidence.compliance_risk, "compliance_risk", max_len=16).upper()
    platform_risk = _text(evidence.platform_risk, "platform_risk", max_len=16).upper()
    duplicate_state = _text(evidence.duplicate_conflict_status, "duplicate_conflict_status", max_len=16).upper()
    if compliance_risk not in _ALLOWED_RISKS or platform_risk not in _ALLOWED_RISKS:
        raise ValueError("risk evidence is invalid")
    if duplicate_state not in _ALLOWED_DUPLICATE_STATES:
        raise ValueError("duplicate/conflict evidence is invalid")

    if isinstance(evidence.cookie_window_days, bool) or not isinstance(evidence.cookie_window_days, int):
        raise TypeError("cookie_window_days must be an integer")
    if evidence.cookie_window_days <= 0 or evidence.cookie_window_days > 365:
        raise ValueError("cookie_window_days outside supported bounds")
    if isinstance(evidence.freshness_ttl_seconds, bool) or not isinstance(evidence.freshness_ttl_seconds, int):
        raise TypeError("freshness_ttl_seconds must be an integer")
    if evidence.freshness_ttl_seconds <= 0 or evidence.freshness_ttl_seconds > 86_400:
        raise ValueError("freshness_ttl_seconds must be within 24 hours")

    disclosures = evidence.disclosure_requirements
    if not isinstance(disclosures, tuple) or not disclosures:
        raise ValueError("disclosure_requirements must be a non-empty tuple")
    normalized_disclosures = [_text(item, "disclosure_requirement", max_len=512) for item in disclosures]
    observed_at = _timestamp(evidence.observed_at, "observed_at")
    deadline = _timestamp(evidence.deadline, "deadline")
    digest = _digest(evidence.evidence_sha256)
    opportunity_id = _opportunity_id(evidence)

    return {
        "opportunity_id": opportunity_id,
        "source_platform": "awin",
        "campaign_id": str(advertiser_id),
        "title": f"Awin affiliate: {program_name}",
        "category": category,
        "publisher_id": publisher_id,
        "advertiser_id": advertiser_id,
        "promotional_channel": channel,
        "tracking_click_ref": f"workflow-os:{opportunity_id}",
        "program_evidence_sha256": digest,
        "rights_verification_state": "VERIFIED",
        "usage_rights": _text(evidence.usage_rights, "usage_rights"),
        "disclosure_requirements": normalized_disclosures,
        "compliance_risk": compliance_risk,
        "platform_risk": platform_risk,
        "duplicate_conflict_status": duplicate_state,
        "expected_owner_minutes": 0.0,
        "user_attention_requirement": "NONE",
        "source_checked_at": observed_at,
        "freshness_ttl_seconds": evidence.freshness_ttl_seconds,
        "deadline": deadline,
        "remaining_budget": gross,
        "payout_formula": f"AWIN_{model}_{'PERCENT' if evidence.commission_rate_is_percent else 'FIXED'}",
        "payout_cap": gross,
        "payment_method": _text(evidence.payment_method, "payment_method"),
        "approval_rules": _text(evidence.approval_rules, "approval_rules"),
        "originality_requirements": _text(evidence.originality_requirements, "originality_requirements"),
        "account_requirements": ["approved_awin_publisher", "approved_advertiser_program"],
        "expected_revenue": gross,
        "expected_production_cost": production_cost,
        "expected_laptop_minutes": laptop_minutes,
        "estimated_success_probability": approval,
        "probability_collection": 1.0,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital,
        "cookie_window_days": evidence.cookie_window_days,
        "commission_rate": rate,
        "commission_model": model,
        "forecast_only": True,
        "proves_received_cash": False,
        "allowed_countries": [],
        "platforms": [channel.lower()],
        "source_assets": [],
        "discovered_at": observed_at,
    }
