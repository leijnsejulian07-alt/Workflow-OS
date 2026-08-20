from __future__ import annotations

import math
from dataclasses import dataclass, asdict


POLICY_VERSION = "realized-cash-learning/1"


@dataclass(frozen=True)
class RealizedCashDecision:
    opportunity_id: str
    action: str
    reasons: tuple[str, ...]
    realized_cash_eur: float
    reconciled_cost_eur: float
    realized_profit_eur: float
    sample_count: int
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def _finite_nonnegative(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def decide_from_realized_cash(
    opportunity_id: str,
    *,
    realized_cash_eur: object,
    reconciled_cost_eur: object,
    sample_count: object,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> RealizedCashDecision:
    """Choose a conservative learning action from reconciled evidence only.

    Forecasts never enter this policy. Missing/invalid evidence fails closed to PAUSE.
    Negative realized margin KILLs the opportunity. Positive evidence can KEEP after
    one sample and SCALE only after a bounded minimum sample count and profit floor.
    """
    opportunity_id = str(opportunity_id or "").strip()
    cash = _finite_nonnegative(realized_cash_eur)
    cost = _finite_nonnegative(reconciled_cost_eur)
    scale_profit = _finite_nonnegative(min_realized_profit_to_scale_eur)
    if (
        not opportunity_id
        or cash is None
        or cost is None
        or scale_profit is None
        or not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 0
        or not isinstance(min_samples_to_scale, int)
        or isinstance(min_samples_to_scale, bool)
        or min_samples_to_scale < 1
    ):
        return RealizedCashDecision(
            opportunity_id=opportunity_id or "unknown",
            action="PAUSE",
            reasons=("REALIZED_EVIDENCE_UNKNOWN_OR_INVALID",),
            realized_cash_eur=cash or 0.0,
            reconciled_cost_eur=cost or 0.0,
            realized_profit_eur=0.0,
            sample_count=sample_count if isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count >= 0 else 0,
        )

    profit = cash - cost
    if sample_count == 0:
        return RealizedCashDecision(opportunity_id, "PAUSE", ("NO_RECONCILED_SAMPLES",), cash, cost, profit, sample_count)
    if profit < 0:
        return RealizedCashDecision(opportunity_id, "KILL", ("NEGATIVE_REALIZED_MARGIN",), cash, cost, profit, sample_count)
    if cash <= 0 or profit <= 0:
        return RealizedCashDecision(opportunity_id, "PAUSE", ("NO_POSITIVE_REALIZED_PROFIT",), cash, cost, profit, sample_count)
    if sample_count >= min_samples_to_scale and profit >= scale_profit:
        return RealizedCashDecision(opportunity_id, "SCALE", ("PROVEN_REALIZED_PROFIT",), cash, cost, profit, sample_count)
    return RealizedCashDecision(opportunity_id, "KEEP", ("POSITIVE_REALIZED_PROFIT_INSUFFICIENT_SCALE_EVIDENCE",), cash, cost, profit, sample_count)
