from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .polymarket_clob import estimate_sell_vwap, fetch_book
from .polymarket_gamma import fetch_gamma_market
from .polymarket_paper import PolymarketPaperPolicy, drawdown_decision, should_exit
from .polymarket_paper_state import PolymarketPaperStore
from .polymarket_scanner import FairProbabilityEstimator, _valid_evidence, scan_paper_markets


@dataclass(frozen=True)
class PaperRunSummary:
    scanned: int
    opened: int
    held: int
    exited: int
    stopped: bool
    stop_reason: str | None


def _exit_open_positions(
    *,
    store: PolymarketPaperStore,
    estimator: FairProbabilityEstimator,
    policy: PolymarketPaperPolicy,
    now: datetime,
) -> tuple[int, int, set[str]]:
    """Monitor durable paper positions and settle only against executable evidence.

    External-data failures never invent a fill. Active-market exits require full CLOB
    bid depth. A closed contract settles only when Gamma exposes an unambiguous
    terminal YES value (exactly 0 or 1) for the same durable token identity.
    """
    exited = held = 0
    exited_market_ids: set[str] = set()
    for position in store.open_positions():
        if not position.yes_token_id:
            store.record_decision(position.market_id, should_exit(
                entry_fair_probability=position.entry_fair_probability,
                current_fair_probability=float("nan"),
                hours_to_resolution=float("nan"),
                mispricing_closed=False,
                policy=policy,
            ))
            held += 1
            continue
        try:
            market = fetch_gamma_market(market_id=position.market_id)
            if market.yes_token_id != position.yes_token_id:
                raise ValueError("durable YES token identity mismatch")
            # Once order trading has ended there may be no executable bid book left.
            # For paper accounting, settle only an unambiguous terminal contract value;
            # any non-terminal closed state remains open/fail-closed for later evidence.
            if market.closed and not market.active and market.yes_price in (0.0, 1.0):
                store.close_yes(market_id=position.market_id, exit_price=market.yes_price)
                exited_market_ids.add(position.market_id)
                exited += 1
                continue
            evidence = estimator(market)
            if not _valid_evidence(evidence, now_utc=now):
                raise ValueError("missing or stale fair-value evidence")
            hours_left = (market.resolves_at.astimezone(timezone.utc) - now).total_seconds() / 3600.0
            mispricing_closed = evidence.probability - market.yes_price <= policy.minimum_edge_points / 100.0
            decision = should_exit(
                entry_fair_probability=position.entry_fair_probability,
                current_fair_probability=evidence.probability,
                hours_to_resolution=hours_left,
                mispricing_closed=mispricing_closed,
                policy=policy,
            )
            store.record_decision(position.market_id, decision)
            if decision.action != "PAPER_EXIT":
                held += 1
                continue
            shares = position.stake_usd / position.entry_price
            exit_price = estimate_sell_vwap(fetch_book(position.yes_token_id), shares=shares)
            store.close_yes(market_id=position.market_id, exit_price=exit_price)
            exited_market_ids.add(position.market_id)
            exited += 1
        except (OSError, RuntimeError, TypeError, ValueError):
            # No synthetic settlement price: retain exposure until official market,
            # evidence and full executable bid depth can all be verified.
            held += 1
    return exited, held, exited_market_ids


def run_paper_cycle(*, store: PolymarketPaperStore, estimator: FairProbabilityEstimator, policy: PolymarketPaperPolicy = PolymarketPaperPolicy(), now_utc: datetime | None = None, market_limit: int = 100) -> PaperRunSummary:
    """Run one durable paper-only monitor + scan cycle; live execution is unreachable."""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    now = now.astimezone(timezone.utc)
    account = store.account()
    if account.stopped:
        return PaperRunSummary(0, 0, 0, 0, True, account.stop_reason)

    exited, exit_holds, exited_market_ids = _exit_open_positions(store=store, estimator=estimator, policy=policy, now=now)
    account = store.account()

    # Reserved stakes are not realized losses, so cash drawdown is checked only when
    # no positions are open. Mark-to-market equity can replace this once exit marking
    # is connected.
    if store.open_count() == 0:
        dd = drawdown_decision(bankroll_usd=account.bankroll_usd, peak_bankroll_usd=account.peak_bankroll_usd, policy=policy)
        if dd.action == "STOP":
            store.stop(dd.reason)
            return PaperRunSummary(0, 0, exit_holds, exited, True, dd.reason)

    results = scan_paper_markets(estimator=estimator, bankroll_usd=account.bankroll_usd, open_positions=store.open_count(), policy=policy, now_utc=now, market_limit=market_limit)
    opened = 0
    held = exit_holds
    open_positions = store.open_count()
    cash = store.account().bankroll_usd
    for result in results:
        store.record_decision(result.market_id, result.decision)
        # An exit is an explicit decision based on fresh evidence. Do not let the
        # scanner churn that same market back into exposure during this cycle.
        if result.market_id in exited_market_ids:
            held += 1
            continue
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
    return PaperRunSummary(len(results), opened, held, exited, False, None)
