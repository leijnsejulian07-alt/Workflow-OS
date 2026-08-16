from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any

POLICY_VERSION = "opportunity-decision-policy/1"
SCORING_VERSION = "priority-scoring/1"
BLOCKED_CATEGORIES = {"fake_engagement", "unsafe_financial_claims", "unsafe_medical_claims", "spam"}
ALLOWED_OWNER_ATTENTION = {"NONE", "OWNER_APPROVAL", "KYC", "EXCEPTION", "EMERGENCY"}
PAUSE_OWNER_ATTENTION = {"OWNER_APPROVAL", "KYC", "EXCEPTION", "EMERGENCY"}
ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "BLOCKED"}


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().isoformat()


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


def _known_num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _known_nonnegative_num(value: Any) -> float | None:
    n = _known_num(value)
    return n if n is not None and n >= 0.0 else None


def _known_probability(value: Any) -> float | None:
    n = _known_num(value)
    return n if n is not None and 0.0 <= n <= 1.0 else None


def _known_nonnegative_int(value: Any) -> int | None:
    n = _known_num(value)
    if n is None or n < 0 or not n.is_integer():
        return None
    return int(n)


def _known_risk(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    risk = value.strip().upper()
    return risk if risk in ALLOWED_RISK_LEVELS else None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize(raw: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now_dt = now or utcnow_dt()
    now_iso = now_dt.isoformat()
    success = _known_probability(raw.get("estimated_success_probability"))
    collection = _known_probability(raw.get("probability_collection"))
    owner_minutes = _known_nonnegative_num(raw.get("expected_owner_minutes"))
    gross = _known_nonnegative_num(raw.get("expected_revenue"))
    collectible_raw = raw.get("expected_collectible_revenue")
    if collectible_raw is None:
        collectible_num = gross * success * collection if gross is not None and success is not None and collection is not None else None
    else:
        collectible_num = _known_nonnegative_num(collectible_raw)
    cost = _known_nonnegative_num(raw.get("expected_production_cost"))
    minutes = _known_nonnegative_num(raw.get("expected_laptop_minutes"))
    remaining_budget = _known_nonnegative_num(raw.get("remaining_budget"))
    ttl = _known_nonnegative_int(raw.get("freshness_ttl_seconds"))
    net = collectible_num - cost if collectible_num is not None and cost is not None else None
    if net is None or minutes is None:
        per_hour = None
    else:
        per_hour = net / (minutes / 60.0) if minutes > 0 else net

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
        "expected_collectible_revenue": collectible_num,
        "expected_net_profit": net,
        "expected_laptop_minutes": minutes,
        "expected_owner_minutes": owner_minutes,
        "expected_profit_per_laptop_hour": per_hour,
        "compliance_risk": _known_risk(raw.get("compliance_risk")),
        "platform_risk": _known_risk(raw.get("platform_risk")),
        "duplicate_conflict_status": str(raw.get("duplicate_conflict_status") or "UNKNOWN").upper(),
        "user_attention_requirement": str(raw.get("user_attention_requirement") or "NONE").upper(),
        "rights_verification_state": str(raw.get("rights_verification_state") or "UNKNOWN").upper(),
        "source_checked_at": raw.get("source_checked_at"),
        "freshness_ttl_seconds": ttl,
        "deadline": raw.get("deadline"),
        "remaining_budget": remaining_budget,
        "payout_formula": raw.get("payout_formula"),
        "discovered_at": raw.get("discovered_at") or now_iso,
        "status": "DISCOVERED",
    }


@dataclass(frozen=True)
class OpportunityDecision:
    opportunity_id: str
    decision: str
    decision_reasons: tuple[str, ...]
    eligible_for_queue: bool
    economic_score: float
    priority_score: float
    requires_revalidation: bool
    revalidation_fields: tuple[str, ...]
    owner_attention_requirement: str
    expected_collectible_revenue: float
    expected_net_profit: float
    expected_profit_per_laptop_hour: float
    estimated_total_cost: float
    risk_penalty: float
    freshness_expires_at: str | None
    evaluated_at: str
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision_reasons"] = list(self.decision_reasons)
        data["revalidation_fields"] = list(self.revalidation_fields)
        return data


def _risk_penalty(op: dict[str, Any]) -> float:
    penalty = 0.0
    for field in ("compliance_risk", "platform_risk"):
        risk = _known_risk(op.get(field))
        if risk is None:
            return 4.0
        penalty += {"LOW": 0.0, "MEDIUM": 0.5, "HIGH": 1.0, "BLOCKED": 2.0}[risk]
    return penalty


def _decision(op: dict[str, Any], *, decision: str, reasons: list[str], now: datetime,
              requires_revalidation: bool = False, revalidation_fields: list[str] | None = None,
              priority_score: float = 0.0) -> OpportunityDecision:
    checked = _parse_dt(op.get("source_checked_at"))
    ttl = _known_nonnegative_int(op.get("freshness_ttl_seconds"))
    expiry = checked + timedelta(seconds=ttl) if checked is not None and ttl is not None else None
    return OpportunityDecision(
        opportunity_id=str(op.get("opportunity_id") or "unknown"),
        decision=decision,
        decision_reasons=tuple(reasons or ["UNSPECIFIED"]),
        eligible_for_queue=decision == "ACCEPT",
        economic_score=float(_num(op.get("expected_net_profit"))),
        priority_score=priority_score,
        requires_revalidation=requires_revalidation,
        revalidation_fields=tuple(revalidation_fields or []),
        owner_attention_requirement=str(op.get("user_attention_requirement") or "NONE"),
        expected_collectible_revenue=max(0.0, _num(op.get("expected_collectible_revenue"))),
        expected_net_profit=_num(op.get("expected_net_profit")),
        expected_profit_per_laptop_hour=_num(op.get("expected_profit_per_laptop_hour")),
        estimated_total_cost=max(0.0, _num(op.get("expected_production_cost"))),
        risk_penalty=_risk_penalty(op),
        freshness_expires_at=expiry.isoformat() if expiry is not None else None,
        evaluated_at=now.isoformat(),
    )


def _priority_score(op: dict[str, Any]) -> tuple[float | None, list[str]]:
    required = {
        "expected_time_to_cash_hours": _known_num(op.get("expected_time_to_cash_hours")),
        "automation_completeness": _known_num(op.get("automation_completeness")),
        "capital_required": _known_num(op.get("capital_required")),
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return None, missing
    time_to_cash = required["expected_time_to_cash_hours"]
    automation = required["automation_completeness"]
    capital = required["capital_required"]
    assert time_to_cash is not None and automation is not None and capital is not None
    if time_to_cash < 0 or not 0 <= automation <= 1 or capital < 0:
        return None, ["priority_score_inputs_invalid"]

    profit = max(0.0, _num(op.get("expected_net_profit")))
    collectible = max(0.0, _num(op.get("expected_collectible_revenue")))
    laptop_profit = max(0.0, _num(op.get("expected_profit_per_laptop_hour")))
    profit_n = profit / (profit + 100.0)
    collectible_n = collectible / (collectible + 100.0)
    laptop_n = laptop_profit / (laptop_profit + 100.0)
    time_n = 1.0 / (1.0 + time_to_cash / 24.0)
    capital_n = 1.0 / (1.0 + capital / 100.0)
    risk_n = max(0.0, 1.0 - _risk_penalty(op) / 4.0)
    owner_n = 1.0 if str(op.get("user_attention_requirement") or "NONE") == "NONE" else 0.0
    score = 100.0 * (
        0.22 * profit_n + 0.12 * collectible_n + 0.18 * laptop_n +
        0.14 * time_n + 0.14 * automation + 0.10 * risk_n +
        0.06 * capital_n + 0.04 * owner_n
    )
    return round(score, 6), []


def evaluate(opportunity: dict[str, Any], *, now: datetime | None = None) -> OpportunityDecision:
    now_dt = now or utcnow_dt()
    category = str(opportunity.get("category", "")).lower()

    if category in BLOCKED_CATEGORIES:
        return _decision(opportunity, decision="REJECT", reasons=["PROHIBITED_CATEGORY"], now=now_dt)
    if opportunity.get("rights_verification_state") != "VERIFIED":
        return _decision(opportunity, decision="REJECT", reasons=["RIGHTS_NOT_VERIFIED"], now=now_dt)
    if not str(opportunity.get("usage_rights") or "").strip():
        return _decision(opportunity, decision="REJECT", reasons=["USAGE_RIGHTS_UNCLEAR"], now=now_dt)

    risk_unknown = [field for field in ("compliance_risk", "platform_risk") if _known_risk(opportunity.get(field)) is None]
    if risk_unknown:
        return _decision(opportunity, decision="REVALIDATE", reasons=["RISK_EVIDENCE_UNKNOWN_OR_INVALID"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=risk_unknown)
    if opportunity.get("compliance_risk") == "BLOCKED" or opportunity.get("platform_risk") == "BLOCKED":
        return _decision(opportunity, decision="REJECT", reasons=["RISK_BLOCKED"], now=now_dt)

    owner_minutes = _known_num(opportunity.get("expected_owner_minutes"))
    if owner_minutes is None:
        return _decision(opportunity, decision="REVALIDATE", reasons=["OWNER_WORKLOAD_UNKNOWN"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=["expected_owner_minutes"])
    if owner_minutes < 0:
        return _decision(opportunity, decision="REVALIDATE", reasons=["OWNER_WORKLOAD_INVALID"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=["expected_owner_minutes"])
    if owner_minutes > 0:
        return _decision(opportunity, decision="REJECT", reasons=["RECURRING_OWNER_WORK_REQUIRED"], now=now_dt)

    attention = str(opportunity.get("user_attention_requirement") or "NONE")
    if attention not in ALLOWED_OWNER_ATTENTION:
        return _decision(opportunity, decision="REJECT", reasons=["INVALID_OWNER_ATTENTION_STATE"], now=now_dt)
    if attention in PAUSE_OWNER_ATTENTION:
        return _decision(opportunity, decision="PAUSE", reasons=[f"OWNER_ATTENTION_{attention}"], now=now_dt)

    stale_fields: list[str] = []
    checked = _parse_dt(opportunity.get("source_checked_at"))
    ttl = _known_nonnegative_int(opportunity.get("freshness_ttl_seconds"))
    if ttl is None:
        stale_fields.append("freshness_ttl_seconds")
    if checked is None or checked > now_dt or ttl is None or ttl <= 0 or checked + timedelta(seconds=ttl) <= now_dt:
        stale_fields.append("source_checked_at")
    for field in ("remaining_budget", "payout_formula"):
        if opportunity.get(field) in (None, "", []):
            stale_fields.append(field)
    deadline_raw = opportunity.get("deadline")
    deadline = _parse_dt(deadline_raw)
    if deadline_raw in (None, "", []):
        stale_fields.append("deadline")
    elif deadline is None:
        stale_fields.append("deadline")
    if stale_fields:
        return _decision(opportunity, decision="REVALIDATE", reasons=["VOLATILE_FIELDS_STALE_OR_UNKNOWN"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=stale_fields)
    if deadline <= now_dt:
        return _decision(opportunity, decision="REJECT", reasons=["DEADLINE_EXPIRED"], now=now_dt)

    economic_unknown = [name for name in (
        "expected_revenue",
        "expected_production_cost",
        "expected_laptop_minutes",
        "estimated_success_probability",
        "probability_collection",
        "expected_collectible_revenue",
        "expected_net_profit",
        "expected_profit_per_laptop_hour",
    ) if opportunity.get(name) is None]
    if economic_unknown:
        return _decision(opportunity, decision="REVALIDATE", reasons=["ECONOMIC_INPUTS_UNKNOWN"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=economic_unknown)
    if _num(opportunity.get("expected_collectible_revenue")) <= 0:
        return _decision(opportunity, decision="REJECT", reasons=["COLLECTIBLE_REVENUE_UNSUPPORTED"], now=now_dt)
    if _num(opportunity.get("expected_net_profit")) <= 0:
        return _decision(opportunity, decision="REJECT", reasons=["NON_POSITIVE_EXPECTED_MARGIN"], now=now_dt)
    if _num(opportunity.get("expected_profit_per_laptop_hour")) <= 0:
        return _decision(opportunity, decision="REJECT", reasons=["NON_POSITIVE_LAPTOP_HOUR_PROFIT"], now=now_dt)
    if opportunity.get("duplicate_conflict_status") in {"DUPLICATE", "CONFLICT"}:
        return _decision(opportunity, decision="PAUSE", reasons=["DUPLICATE_OR_CONFLICT"], now=now_dt)

    score, missing = _priority_score(opportunity)
    if score is None:
        return _decision(opportunity, decision="REVALIDATE", reasons=["PRIORITY_INPUTS_UNKNOWN_OR_INVALID"], now=now_dt,
                         requires_revalidation=True, revalidation_fields=missing)
    return _decision(opportunity, decision="ACCEPT", reasons=[SCORING_VERSION], now=now_dt, priority_score=score)
