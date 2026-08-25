from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .trading_simulation import TradingBacktestEvidence, TradingSimulationDecision

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_RISKS = frozenset({"LOW", "MEDIUM", "HIGH", "BLOCKED"})
_MAX_TEXT = 2048


@dataclass(frozen=True)
class TrustedTradingOpportunityEvidence:
    """Workflow OS-owned forecast/risk evidence for a trading candidate.

    This boundary is intentionally simulation-first. It can surface a candidate in
    the central Opportunity Manager, but it cannot grant live-order authority.
    Owner approval is required before any later funded-account/live path may be
    considered, which keeps the generic revenue scheduler from queuing an order.
    """

    strategy_rights_verified: bool
    forecast_verified: bool
    expected_revenue_eur: float
    expected_cost_eur: float
    expected_laptop_minutes: float
    estimated_success_probability: float
    probability_collection: float
    expected_time_to_cash_hours: float
    automation_completeness: float
    capital_required_eur: float
    payout_cap_eur: float
    remaining_budget_eur: float
    compliance_risk: str
    platform_risk: str
    duplicate_conflict_status: str
    payout_formula: str
    payment_method: str
    approval_rules: str
    originality_requirements: str
    deadline: str
    freshness_ttl_seconds: int
    forecast_evidence_sha256: str


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
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def _probability(value: float, name: str) -> float:
    number = _finite_nonnegative(value, name)
    if number > 1:
        raise ValueError(f"{name} must be within [0, 1]")
    return number


def build_trading_opportunity(
    *,
    backtest: TradingBacktestEvidence,
    decision: TradingSimulationDecision,
    evidence: TrustedTradingOpportunityEvidence,
) -> dict[str, object]:
    """Build a central Opportunity Manager payload for a simulation-proven strategy.

    The resulting candidate is intentionally owner-approval PAUSE-only and carries
    ``live_execution_enabled=False``. This makes trading visible to the shared
    Opportunity Manager without allowing a successful backtest or forecast to emit
    a live order or become received-cash evidence.
    """

    if not isinstance(backtest, TradingBacktestEvidence):
        raise TypeError("backtest must be TradingBacktestEvidence")
    if not isinstance(decision, TradingSimulationDecision):
        raise TypeError("decision must be TradingSimulationDecision")
    if not isinstance(evidence, TrustedTradingOpportunityEvidence):
        raise TypeError("evidence must be TrustedTradingOpportunityEvidence")
    if backtest.strategy_id != decision.strategy_id:
        raise ValueError("backtest and decision strategy identity mismatch")
    if backtest.proves_received_cash:
        raise ValueError("backtest evidence may never prove received cash")
    if decision.decision != "SIMULATION_PASS" or decision.may_continue_simulation is not True:
        raise ValueError("only a passed trading simulation may enter opportunity admission")
    if decision.may_enter_live_execution:
        raise ValueError("simulation decision may not grant live execution authority")
    if evidence.strategy_rights_verified is not True or evidence.forecast_verified is not True:
        raise ValueError("trusted trading opportunity evidence is incomplete")
    if not _SHA256_RE.fullmatch(evidence.forecast_evidence_sha256):
        raise ValueError("forecast evidence digest is malformed")

    expected_revenue = _finite_nonnegative(evidence.expected_revenue_eur, "expected_revenue_eur")
    expected_cost = _finite_nonnegative(evidence.expected_cost_eur, "expected_cost_eur")
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
    payout_cap = _finite_nonnegative(evidence.payout_cap_eur, "payout_cap_eur")
    remaining_budget = _finite_nonnegative(evidence.remaining_budget_eur, "remaining_budget_eur")

    if expected_revenue <= 0:
        raise ValueError("trading forecast must have positive expected revenue")
    if expected_revenue > payout_cap:
        raise ValueError("expected revenue exceeds independently verified payout cap")
    if expected_revenue > remaining_budget:
        raise ValueError("expected revenue exceeds independently verified remaining budget")
    if expected_revenue * success_probability * collection_probability <= expected_cost:
        raise ValueError("trading opportunity has non-positive expected collectible margin")

    compliance_risk = _text(evidence.compliance_risk, "compliance_risk", max_len=16).upper()
    platform_risk = _text(evidence.platform_risk, "platform_risk", max_len=16).upper()
    if compliance_risk not in _ALLOWED_RISKS or platform_risk not in _ALLOWED_RISKS:
        raise ValueError("risk evidence is invalid")
    if compliance_risk == "BLOCKED" or platform_risk == "BLOCKED":
        raise ValueError("blocked trading risk may not enter opportunity admission")

    duplicate_state = _text(
        evidence.duplicate_conflict_status, "duplicate_conflict_status", max_len=16
    ).upper()
    if duplicate_state not in {"CLEAR", "DUPLICATE", "CONFLICT"}:
        raise ValueError("duplicate/conflict evidence is invalid")

    if isinstance(evidence.freshness_ttl_seconds, bool) or not isinstance(
        evidence.freshness_ttl_seconds, int
    ):
        raise TypeError("freshness_ttl_seconds must be an integer")
    if not 1 <= evidence.freshness_ttl_seconds <= 86_400:
        raise ValueError("freshness_ttl_seconds must be within 1 second and 24 hours")

    return {
        "source_platform": "trading_simulation",
        "campaign_id": backtest.strategy_id,
        "title": f"Trading strategy candidate: {backtest.strategy_id}",
        "category": "trading",
        "rights_verification_state": "VERIFIED",
        "usage_rights": "strategy/backtest authorized for Workflow OS simulation evaluation",
        "strategy_id": backtest.strategy_id,
        "simulation_engine": backtest.engine,
        "simulation_engine_version": backtest.engine_version,
        "simulation_evidence_sha256": backtest.evidence_sha256,
        "forecast_evidence_sha256": evidence.forecast_evidence_sha256,
        "simulation_decision": decision.decision,
        "execution_mode": "SIMULATION_ONLY",
        "live_execution_enabled": False,
        "proves_received_cash": False,
        "compliance_risk": compliance_risk,
        "platform_risk": platform_risk,
        "duplicate_conflict_status": duplicate_state,
        "expected_owner_minutes": 0.0,
        "user_attention_requirement": "OWNER_APPROVAL",
        "source_checked_at": backtest.observed_at,
        "freshness_ttl_seconds": evidence.freshness_ttl_seconds,
        "deadline": _text(evidence.deadline, "deadline", max_len=128),
        "remaining_budget": remaining_budget,
        "payout_formula": _text(evidence.payout_formula, "payout_formula"),
        "payout_cap": payout_cap,
        "payment_method": _text(evidence.payment_method, "payment_method"),
        "approval_rules": _text(evidence.approval_rules, "approval_rules"),
        "originality_requirements": _text(
            evidence.originality_requirements, "originality_requirements"
        ),
        "account_requirements": ["owner approval required before funded-account live gate"],
        "expected_revenue": expected_revenue,
        "expected_production_cost": expected_cost,
        "expected_laptop_minutes": laptop_minutes,
        "estimated_success_probability": success_probability,
        "probability_collection": collection_probability,
        "expected_time_to_cash_hours": time_to_cash,
        "automation_completeness": automation,
        "capital_required": capital,
        "allowed_countries": [],
        "platforms": ["funded_trading"],
        "source_assets": [],
        "disclosure_requirements": [],
        "discovered_at": backtest.observed_at,
    }
