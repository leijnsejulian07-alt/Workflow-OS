from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

BLOCKED_CATEGORIES = {"fake_engagement", "unsafe_financial_claims", "unsafe_medical_claims", "spam"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(raw: dict[str, Any]) -> str:
    if raw.get("opportunity_id"):
        return str(raw["opportunity_id"])
    key = "|".join(str(raw.get(k, "")) for k in ("source_platform", "campaign_id", "title"))
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    success = min(1.0, max(0.0, _num(raw.get("estimated_success_probability"), 0.0)))
    collection = min(1.0, max(0.0, _num(raw.get("probability_collection"), 1.0)))
    gross = max(0.0, _num(raw.get("expected_revenue"), 0.0))
    collectible = raw.get("expected_collectible_revenue")
    if collectible is None:
        collectible = gross * success * collection
    collectible = max(0.0, _num(collectible))
    cost = max(0.0, _num(raw.get("expected_production_cost"), 0.0))
    minutes = max(0.0, _num(raw.get("expected_laptop_minutes"), 0.0))
    net = collectible - cost
    per_hour = net / (minutes / 60.0) if minutes > 0 else net
    now = utcnow()

    return {
        **raw,
        "opportunity_id": _id(raw),
        "source_platform": str(raw.get("source_platform") or "unknown"),
        "campaign_id": raw.get("campaign_id"),
        "title": str(raw.get("title") or "Untitled opportunity"),
        "category": str(raw.get("category") or "unknown"),
        "allowed_countries": list(raw.get("allowed_countries") or []),
        "platforms": list(raw.get("platforms") or []),
        "source_assets": list(raw.get("source_assets") or []),
        "usage_rights": str(raw.get("usage_rights") or ""),
        "disclosure_requirements": list(raw.get("disclosure_requirements") or []),
        "account_requirements": list(raw.get("account_requirements") or []),
        "expected_production_cost": cost,
        "estimated_success_probability": success,
        "probability_collection": collection,
        "expected_revenue": gross,
        "expected_collectible_revenue": collectible,
        "expected_net_profit": net,
        "expected_laptop_minutes": minutes,
        "expected_owner_minutes": max(0.0, _num(raw.get("expected_owner_minutes"), 0.0)),
        "expected_profit_per_laptop_hour": per_hour,
        "compliance_risk": str(raw.get("compliance_risk") or "MEDIUM").upper(),
        "platform_risk": str(raw.get("platform_risk") or "MEDIUM").upper(),
        "duplicate_conflict_status": str(raw.get("duplicate_conflict_status") or "UNKNOWN").upper(),
        "user_attention_requirement": str(raw.get("user_attention_requirement") or "NONE").upper(),
        "rights_verification_state": str(raw.get("rights_verification_state") or "UNKNOWN").upper(),
        "source_checked_at": str(raw.get("source_checked_at") or now),
        "freshness_ttl_seconds": max(0, int(_num(raw.get("freshness_ttl_seconds"), 3600))),
        "discovered_at": raw.get("discovered_at") or now,
        "status": "DISCOVERED",
    }


@dataclass(frozen=True)
class Eligibility:
    accepted: bool
    reason: str | None


def evaluate(opportunity: dict[str, Any]) -> Eligibility:
    category = str(opportunity.get("category", "")).lower()
    if category in BLOCKED_CATEGORIES:
        return Eligibility(False, "PROHIBITED_CATEGORY")
    if opportunity.get("rights_verification_state") != "VERIFIED":
        return Eligibility(False, "RIGHTS_NOT_VERIFIED")
    if opportunity.get("compliance_risk") == "BLOCKED" or opportunity.get("platform_risk") == "BLOCKED":
        return Eligibility(False, "RISK_BLOCKED")
    if opportunity.get("duplicate_conflict_status") in {"DUPLICATE", "CONFLICT"}:
        return Eligibility(False, "DUPLICATE_OR_CONFLICT")
    if _num(opportunity.get("expected_net_profit")) <= 0:
        return Eligibility(False, "NON_POSITIVE_EXPECTED_MARGIN")
    if _num(opportunity.get("expected_owner_minutes")) > 0:
        return Eligibility(False, "RECURRING_OWNER_WORK_REQUIRED")
    if opportunity.get("user_attention_requirement") not in {"NONE", "OWNER_APPROVAL", "KYC", "EXCEPTION", "EMERGENCY"}:
        return Eligibility(False, "INVALID_OWNER_ATTENTION_STATE")
    return Eligibility(True, None)


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))
