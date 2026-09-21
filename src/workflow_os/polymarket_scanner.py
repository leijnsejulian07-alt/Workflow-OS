from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .polymarket_clob import estimate_buy_slippage, fetch_book
from .polymarket_gamma import GammaMarket, fetch_gamma_markets
from .polymarket_paper import PolymarketCandidate, PolymarketPaperDecision, PolymarketPaperPolicy, evaluate_candidate


@dataclass(frozen=True)
class FairProbabilityEvidence:
    probability: float
    source: str
    observed_at: datetime


@dataclass(frozen=True)
class PaperScanResult:
    market_id: str
    question: str
    decision: PolymarketPaperDecision
    evidence_source: str = ""
    market_price: float | None = None
    fair_probability: float | None = None


FairProbabilityEstimator = Callable[[GammaMarket], FairProbabilityEvidence | None]
DEFAULT_MAX_EVIDENCE_AGE = timedelta(minutes=15)


def _valid_evidence(
    evidence: FairProbabilityEvidence | None,
    *,
    now_utc: datetime,
    max_age: timedelta = DEFAULT_MAX_EVIDENCE_AGE,
) -> bool:
    # Estimators are an external-input boundary. Never let malformed model/provider
    # output crash the whole scanner or reach the CLOB path.
    if not isinstance(evidence, FairProbabilityEvidence):
        return False
    if not isinstance(evidence.source, str) or not evidence.source.strip():
        return False
    probability = evidence.probability
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        return False
    if not math.isfinite(float(probability)) or not 0.0 < float(probability) < 1.0:
        return False
    if not isinstance(evidence.observed_at, datetime):
        return False
    if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
        return False
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        return False
    observed = evidence.observed_at.astimezone(timezone.utc)
    return now_utc - max_age <= observed <= now_utc


def scan_paper_markets(*, estimator: FairProbabilityEstimator, bankroll_usd: float, open_positions: int, policy: PolymarketPaperPolicy = PolymarketPaperPolicy(), now_utc: datetime | None = None, market_limit: int = 100, max_evidence_age: timedelta = DEFAULT_MAX_EVIDENCE_AGE) -> list[PaperScanResult]:
    """Read-only Gamma -> fresh evidence -> CLOB -> guide gate scanner."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now_utc is not None and (now_utc.tzinfo is None or now_utc.utcoffset() is None):
        raise ValueError("now_utc must be timezone-aware")

    results: list[PaperScanResult] = []
    for market in fetch_gamma_markets(limit=market_limit):
        try:
            evidence = estimator(market)
        except Exception:
            evidence = None
        if not _valid_evidence(evidence, now_utc=now, max_age=max_evidence_age):
            results.append(PaperScanResult(market.market_id, market.question, PolymarketPaperDecision("HOLD", "MISSING_OR_STALE_FAIR_VALUE_EVIDENCE")))
            continue
        max_stake = bankroll_usd * policy.maximum_bankroll_fraction
        try:
            book = fetch_book(market.yes_token_id)
            slippage = estimate_buy_slippage(book, stake_usd=max_stake)
        except (OSError, RuntimeError, TypeError, ValueError):
            results.append(PaperScanResult(market.market_id, market.question, PolymarketPaperDecision("HOLD", "CLOB_DATA_UNAVAILABLE"), evidence.source))
            continue
        candidate = PolymarketCandidate(market.market_id, market.yes_price, evidence.probability, market.liquidity_usd, market.resolves_at, market.resolution_source_present, slippage)
        decision = evaluate_candidate(candidate=candidate, bankroll_usd=bankroll_usd, open_positions=open_positions, policy=policy, now_utc=now)
        results.append(PaperScanResult(market.market_id, market.question, decision, evidence.source, market.yes_price, evidence.probability))
    return results
