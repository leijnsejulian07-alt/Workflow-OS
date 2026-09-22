from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

POLYMARKET_PAPER_POLICY_VERSION = "polymarket-guide-paper/1"


@dataclass(frozen=True)
class PolymarketPaperPolicy:
    starting_bankroll_usd: float = 50.0
    minimum_liquidity_usd: float = 5_000.0
    minimum_hours_to_resolution: float = 2.0
    minimum_edge_points: float = 8.0
    maximum_exit_slippage: float = 0.03
    kelly_fraction: float = 0.5
    maximum_bankroll_fraction: float = 0.06
    maximum_open_positions: int = 5
    drawdown_stop_fraction: float = 0.40
    fair_value_exit_change_points: float = 5.0
    exit_within_hours: float = 1.0


@dataclass(frozen=True)
class PolymarketCandidate:
    market_id: str
    market_price: float
    fair_probability: float
    liquidity_usd: float
    resolves_at: datetime
    official_resolution_source_verified: bool
    estimated_exit_slippage: float


@dataclass(frozen=True)
class PolymarketPaperDecision:
    action: str
    reason: str
    stake_usd: float = 0.0
    edge_points: float = 0.0


def _finite_probability(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and 0.0 < float(value) < 1.0


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def evaluate_candidate(
    *, candidate: PolymarketCandidate, bankroll_usd: float, open_positions: int,
    policy: PolymarketPaperPolicy = PolymarketPaperPolicy(), now_utc: datetime | None = None,
) -> PolymarketPaperDecision:
    """Guide-faithful paper-only entry gate. No external side effect is reachable here."""
    if not candidate.market_id or candidate.market_id != candidate.market_id.strip():
        return PolymarketPaperDecision("HOLD", "INVALID_MARKET_ID")
    if not _finite_probability(candidate.market_price) or not _finite_probability(candidate.fair_probability):
        return PolymarketPaperDecision("HOLD", "INVALID_PROBABILITY")
    if not math.isfinite(bankroll_usd) or bankroll_usd <= 0:
        return PolymarketPaperDecision("STOP", "BANKROLL_DEPLETED")
    if open_positions < 0 or open_positions >= policy.maximum_open_positions:
        return PolymarketPaperDecision("HOLD", "OPEN_POSITION_LIMIT")
    if candidate.official_resolution_source_verified is not True:
        return PolymarketPaperDecision("HOLD", "UNVERIFIED_RESOLUTION_SOURCE")
    if not math.isfinite(candidate.liquidity_usd) or candidate.liquidity_usd < policy.minimum_liquidity_usd:
        return PolymarketPaperDecision("HOLD", "INSUFFICIENT_LIQUIDITY")
    resolves_at = _utc(candidate.resolves_at)
    hours_left = (resolves_at - _utc(now_utc)).total_seconds() / 3600.0
    if hours_left < policy.minimum_hours_to_resolution:
        return PolymarketPaperDecision("HOLD", "TOO_CLOSE_TO_RESOLUTION")
    if not math.isfinite(candidate.estimated_exit_slippage) or candidate.estimated_exit_slippage < 0 or candidate.estimated_exit_slippage > policy.maximum_exit_slippage:
        return PolymarketPaperDecision("HOLD", "EXIT_LIQUIDITY_RISK")

    edge_points = (candidate.fair_probability - candidate.market_price) * 100.0
    if edge_points <= policy.minimum_edge_points:
        return PolymarketPaperDecision("HOLD", "EDGE_BELOW_THRESHOLD", edge_points=edge_points)

    price = candidate.market_price
    p = candidate.fair_probability
    b = (1.0 - price) / price
    full_kelly = (b * p - (1.0 - p)) / b
    if not math.isfinite(full_kelly) or full_kelly <= 0:
        return PolymarketPaperDecision("HOLD", "NONPOSITIVE_KELLY", edge_points=edge_points)
    fraction = min(full_kelly * policy.kelly_fraction, policy.maximum_bankroll_fraction)
    stake = bankroll_usd * fraction
    if not math.isfinite(stake) or stake <= 0:
        return PolymarketPaperDecision("HOLD", "INVALID_STAKE", edge_points=edge_points)
    return PolymarketPaperDecision("PAPER_BUY_YES", "GUIDE_SIGNAL", round(stake, 8), edge_points)


def drawdown_decision(*, bankroll_usd: float, peak_bankroll_usd: float, policy: PolymarketPaperPolicy = PolymarketPaperPolicy()) -> PolymarketPaperDecision:
    if not math.isfinite(bankroll_usd) or not math.isfinite(peak_bankroll_usd) or peak_bankroll_usd <= 0:
        return PolymarketPaperDecision("STOP", "INVALID_BANKROLL_STATE")
    if bankroll_usd <= 0:
        return PolymarketPaperDecision("STOP", "BANKROLL_DEPLETED")
    drawdown = 1.0 - bankroll_usd / peak_bankroll_usd
    if drawdown >= policy.drawdown_stop_fraction:
        return PolymarketPaperDecision("STOP", "DRAWDOWN_LIMIT")
    return PolymarketPaperDecision("CONTINUE", "WITHIN_DRAWDOWN_LIMIT")


def should_exit(*, entry_fair_probability: float, current_fair_probability: float, hours_to_resolution: float, mispricing_closed: bool, policy: PolymarketPaperPolicy = PolymarketPaperPolicy()) -> PolymarketPaperDecision:
    """Fail-safe paper exit gate: malformed monitoring input reduces exposure rather than silently holding."""
    if (
        not _finite_probability(entry_fair_probability)
        or not _finite_probability(current_fair_probability)
        or not isinstance(hours_to_resolution, (int, float))
        or isinstance(hours_to_resolution, bool)
        or not math.isfinite(float(hours_to_resolution))
        or not isinstance(mispricing_closed, bool)
    ):
        return PolymarketPaperDecision("PAPER_EXIT", "INVALID_EXIT_INPUT")
    if mispricing_closed:
        return PolymarketPaperDecision("PAPER_EXIT", "MISPRICING_CLOSED")
    if abs(current_fair_probability - entry_fair_probability) * 100.0 > policy.fair_value_exit_change_points:
        return PolymarketPaperDecision("PAPER_EXIT", "FAIR_VALUE_CHANGED")
    if hours_to_resolution <= policy.exit_within_hours:
        return PolymarketPaperDecision("PAPER_EXIT", "RESOLUTION_WINDOW")
    return PolymarketPaperDecision("HOLD", "KEEP_POSITION")
