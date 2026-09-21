from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .polymarket_paper import PolymarketPaperPolicy, drawdown_decision
from .polymarket_paper_state import PolymarketPaperStore
from .polymarket_scanner import FairProbabilityEstimator, PaperScanResult, scan_paper_markets


@dataclass(frozen=True)
class PaperRunSummary:
    scanned: int
    opened: int
    held: int
    stopped: bool
    stop_reason: str | None


def run_paper_cycle(
    *,
    store: PolymarketPaperStore,
    estimator: FairProbabilityEstimator,
    policy: PolymarketPaperPolicy = PolymarketPaperPolicy(),
    now_utc: datetime | None = None,
    market_limit: int = 100,
) -> PaperRunSummary:
    """Execute one durable paper-only scan cycle.

    No live trading side effect is reachable from this module. Decisions are written
    to SQLite before paper positions are opened. Existing/stopped state fails closed.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")

    account = store.account()
    if account.stopped:
        return PaperRunSummary(0, 0, 0, True, account.stop_reason)

    # Only realized cash drawdown is enforced here. Reserved stake for currently open
    # positions must not be mistaken for a realized loss.
    if store.open_count() == 0:
        dd = drawdown_decision(
            bankroll_usd=account.bankroll_usd,
            peak_bankroll_usd=account.peak_bankroll_usd,
            policy=policy,
        )
        if dd.action == "STOP":
            store.stop(dd.reason)
            return PaperRunSummary(0, 0, 0, True, dd.reason)

    results = scan_paper_markets(
        estimator=estimator,
        bankroll_usd=account.bankroll_usd,
        open_positions=store.open_count(),
        policy=policy,
        now_utc=now,
        market_limit=market_limit,
    )

    opened = 0
    held = 0
    open_positions = store.open_count()
    cash = store.account().bankroll_usd
    for result in results:
        store.record_decision(result.market_id, result.decision)
        if result.decision.action != "PAPER_BUY_YES":
            held += 1
            continue
        if open_positions >= policy.maximum_open_positions:
            held += 1
            continue
        stake = min(result.decision.stake_usd, cash)
        if stake <= 0:
            held += 1
            continue

        # The scanner's signal contains the guide-sized stake but not the normalized
        # market/evidence values needed by the ledger. Re-evaluating those externally
        # would create a race, so opening is intentionally deferred until the scanner
        # exposes an immutable execution snapshot.
        held += 1

    return PaperRunSummary(len(results), opened, held, False, None)
