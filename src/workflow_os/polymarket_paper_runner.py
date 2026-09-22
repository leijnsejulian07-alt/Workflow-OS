from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .polymarket_paper import PolymarketPaperPolicy, drawdown_decision
from .polymarket_paper_state import PolymarketPaperStore
from .polymarket_scanner import FairProbabilityEstimator, scan_paper_markets


@dataclass(frozen=True)
class PaperRunSummary:
    scanned: int
    opened: int
    held: int
    stopped: bool
    stop_reason: str | None


def run_paper_cycle(*, store: PolymarketPaperStore, estimator: FairProbabilityEstimator, policy: PolymarketPaperPolicy = PolymarketPaperPolicy(), now_utc: datetime | None = None, market_limit: int = 100) -> PaperRunSummary:
    """Run one durable paper-only scan cycle; live execution is unreachable."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    account = store.account()
    if account.stopped:
        return PaperRunSummary(0, 0, 0, True, account.stop_reason)

    # Reserved stakes are not realized losses, so cash drawdown is checked only when
    # no positions are open. Mark-to-market equity can replace this once exit marking
    # is connected.
    if store.open_count() == 0:
        dd = drawdown_decision(bankroll_usd=account.bankroll_usd, peak_bankroll_usd=account.peak_bankroll_usd, policy=policy)
        if dd.action == "STOP":
            store.stop(dd.reason)
            return PaperRunSummary(0, 0, 0, True, dd.reason)

    results = scan_paper_markets(estimator=estimator, bankroll_usd=account.bankroll_usd, open_positions=store.open_count(), policy=policy, now_utc=now, market_limit=market_limit)
    opened = held = 0
    open_positions = store.open_count()
    cash = store.account().bankroll_usd
    for result in results:
        store.record_decision(result.market_id, result.decision)
        if result.decision.action != "PAPER_BUY_YES" or open_positions >= policy.maximum_open_positions:
            held += 1
            continue
        if result.market_price is None or result.fair_probability is None:
            held += 1
            continue
        # Asset identity is required for a restart-safe executable exit. Never open a
        # new position that the monitoring worker cannot map back to the YES book.
        if not isinstance(result.yes_token_id, str) or not result.yes_token_id or result.yes_token_id != result.yes_token_id.strip():
            held += 1
            continue
        stake = min(result.decision.stake_usd, cash)
        if stake <= 0:
            held += 1
            continue
        try:
            store.open_yes(
                market_id=result.market_id,
                stake_usd=stake,
                entry_price=result.market_price,
                entry_fair_probability=result.fair_probability,
                opened_at=now,
                yes_token_id=result.yes_token_id,
            )
        except (KeyError, RuntimeError, ValueError):
            held += 1
            continue
        cash -= stake
        open_positions += 1
        opened += 1
    return PaperRunSummary(len(results), opened, held, False, None)
