from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .polymarket_clob import estimate_buy_slippage, fetch_book
from .polymarket_gamma import GammaMarket, fetch_gamma_markets
from .polymarket_paper import (
    PolymarketCandidate,
    PolymarketPaperDecision,
    PolymarketPaperPolicy,
    evaluate_candidate,
)


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


FairProbabilityEstimator = Callable[[GammaMarket], FairProbabilityEvidence | None]


def _valid_evidence(evidence: FairProbabilityEvidence | None, *, now_utc: datetime) -> bool:
    if evidence is None or not evidence.source.strip():
        return False
    if not 0.0 < evidence.probability < 1.0:
        return False
    if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
        return False
    observed = evidence.observed_at.astimezone(timezone.utc)
    # Future-dated evidence is invalid. Staleness policy is estimator-specific and must
    # be enforced by the estimator because acceptable age depends on the evidence type.
    return observed <= now_utc


def scan_paper_markets(
    *,
    estimator: FairProbabilityEstimator,
    bankroll_usd: float,
    open_positions: int,
    policy: PolymarketPaperPolicy = PolymarketPaperPolicy(),
    now_utc: datetime | None = None,
    market_limit: int = 100,
) -> list[PaperScanResult]:
    """Read-only Gamma -> evidence -> CLOB -> guide gate scanner.

    This function cannot place an order. Missing/invalid evidence and market-data
    failures fail closed per market so one bad market does not stop the scan.
    """
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now_utc is not None and (now_utc.tzinfo is None or now_utc.utcoffset() is None):
        raise ValueError("now_utc must be timezone-aware")

    results: list[PaperScanResult] = []
    for market in fetch_gamma_markets(limit=market_limit):
        try:
            evidence = estimator(market)
        except Exception:
            evidence = None
        if not _valid_evidence(evidence, now_utc=now):
            results.append(PaperScanResult(market.market_id, market.question, PolymarketPaperDecision("HOLD", "MISSING_FAIR_VALUE_EVIDENCE")))
            continue

        # Conservative pre-gate slippage check at the maximum stake this policy could
        # permit. The final guide gate can only choose an equal or smaller stake.
        max_stake = bankroll_usd * policy.maximum_bankroll_fraction
        try:
            book = fetch_book(market.yes_token_id)
            slippage = estimate_buy_slippage(book, stake_usd=max_stake)
        except (OSError, RuntimeError, TypeError, ValueError):
            results.append(PaperScanResult(market.market_id, market.question, PolymarketPaperDecision("HOLD", "CLOB_DATA_UNAVAILABLE"), evidence.source))
            continue

        candidate = PolymarketCandidate(
            market_id=market.market_id,
            market_price=market.yes_price,
            fair_probability=evidence.probability,
            liquidity_usd=market.liquidity_usd,
            resolves_at=market.resolves_at,
            official_resolution_source_verified=market.resolution_source_present,
            estimated_exit_slippage=slippage,
        )
        decision = evaluate_candidate(
            candidate=candidate,
            bankroll_usd=bankroll_usd,
            open_positions=open_positions,
            policy=policy,
            now_utc=now,
        )
        results.append(PaperScanResult(market.market_id, market.question, decision, evidence.source))
    return results
