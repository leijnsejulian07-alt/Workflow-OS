from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class ProviderOperationalConstraints:
    provider: str
    program: str
    minimum_trade_duration_seconds: float
    minimum_trade_share_at_or_above_duration_pct: float
    minimum_profit_share_at_or_above_duration_pct: float
    max_idle_calendar_days: int
    source_url: str
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationalComplianceDecision:
    decision: str
    reasons: tuple[str, ...]
    qualifying_trade_share_pct: float
    qualifying_profit_share_pct: float
    idle_days: float


def tradeify_growth_operational_constraints() -> ProviderOperationalConstraints:
    """Current funded-account payout/idle constraints from Tradeify's official trader guidelines.

    These constraints are intentionally separate from provider capability/readiness.
    Passing them never authorizes an order; they only prevent strategies that would
    be payout-ineligible or account-inactive under current published rules.
    """
    return ProviderOperationalConstraints(
        provider="Tradeify",
        program="Growth Sim Funded",
        minimum_trade_duration_seconds=10.0,
        minimum_trade_share_at_or_above_duration_pct=50.0,
        minimum_profit_share_at_or_above_duration_pct=50.0,
        max_idle_calendar_days=7,
        source_url="https://help.tradeify.co/en/articles/10468318-guidelines-for-traders",
        checked_at="2026-08-26T01:15:00+02:00",
    )


def _finite_nonnegative(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and nonnegative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def assess_operational_compliance(
    constraints: ProviderOperationalConstraints,
    *,
    trade_durations_seconds: Iterable[float],
    realized_trade_profits: Iterable[float],
    last_trade_at: datetime,
    now: datetime | None = None,
) -> OperationalComplianceDecision:
    """Fail closed on payout-eligibility and account-idle constraints.

    The two iterables are parallel per-trade observations. Profit-share is computed
    from positive realized profit only; losses cannot make a microscalping-heavy
    strategy look compliant. This function has no execution side effects.
    """
    durations = [_finite_nonnegative(v, name="trade duration") for v in trade_durations_seconds]
    profits = []
    for value in realized_trade_profits:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("realized trade profit must be finite") from exc
        if not math.isfinite(number):
            raise ValueError("realized trade profit must be finite")
        profits.append(number)

    if len(durations) != len(profits):
        raise ValueError("trade durations and profits must have equal length")
    if not durations:
        return OperationalComplianceDecision(
            decision="HOLD",
            reasons=("NO_TRADE_EVIDENCE",),
            qualifying_trade_share_pct=0.0,
            qualifying_profit_share_pct=0.0,
            idle_days=0.0,
        )
    if last_trade_at.tzinfo is None:
        raise ValueError("last_trade_at must be timezone-aware")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)
    last_trade_utc = last_trade_at.astimezone(timezone.utc)
    if last_trade_utc > observed_now + timedelta(minutes=5):
        return OperationalComplianceDecision(
            decision="HOLD",
            reasons=("LAST_TRADE_FROM_FUTURE",),
            qualifying_trade_share_pct=0.0,
            qualifying_profit_share_pct=0.0,
            idle_days=0.0,
        )

    threshold = constraints.minimum_trade_duration_seconds
    qualifying = [duration >= threshold for duration in durations]
    qualifying_trade_share = 100.0 * sum(qualifying) / len(qualifying)

    positive_profit_total = sum(max(0.0, profit) for profit in profits)
    qualifying_positive_profit = sum(
        max(0.0, profit) for is_qualifying, profit in zip(qualifying, profits) if is_qualifying
    )
    qualifying_profit_share = (
        100.0 * qualifying_positive_profit / positive_profit_total if positive_profit_total > 0 else 0.0
    )
    idle_days = max(0.0, (observed_now - last_trade_utc).total_seconds() / 86400.0)

    reasons: list[str] = []
    if qualifying_trade_share <= constraints.minimum_trade_share_at_or_above_duration_pct:
        reasons.append("TRADE_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE")
    if qualifying_profit_share <= constraints.minimum_profit_share_at_or_above_duration_pct:
        reasons.append("PROFIT_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE")
    if idle_days > constraints.max_idle_calendar_days:
        reasons.append("ACCOUNT_IDLE_LIMIT_EXCEEDED")

    if reasons:
        return OperationalComplianceDecision(
            decision="HOLD",
            reasons=tuple(reasons),
            qualifying_trade_share_pct=qualifying_trade_share,
            qualifying_profit_share_pct=qualifying_profit_share,
            idle_days=idle_days,
        )

    return OperationalComplianceDecision(
        decision="ELIGIBLE",
        reasons=("OPERATIONAL_CONSTRAINTS_PASSED",),
        qualifying_trade_share_pct=qualifying_trade_share,
        qualifying_profit_share_pct=qualifying_profit_share,
        idle_days=idle_days,
    )
