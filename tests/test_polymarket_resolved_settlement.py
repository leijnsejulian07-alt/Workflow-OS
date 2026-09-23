from datetime import datetime, timedelta, timezone

import pytest

from workflow_os.polymarket_gamma import GammaMarket
from workflow_os.polymarket_paper_runner import run_paper_cycle
from workflow_os.polymarket_paper_state import PolymarketPaperStore


@pytest.mark.parametrize(
    ("terminal_yes_price", "expected_bankroll"),
    [(1.0, 52.0), (0.0, 47.0)],
)
def test_runner_settles_closed_market_without_clob_depth(
    monkeypatch, tmp_path, terminal_yes_price, expected_bankroll
):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    now = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
    store.open_yes(
        market_id="m1",
        stake_usd=3.0,
        entry_price=0.60,
        entry_fair_probability=0.75,
        opened_at=now - timedelta(days=1),
        yes_token_id="yes-token-1",
    )
    resolved = GammaMarket(
        "m1",
        "Question?",
        terminal_yes_price,
        "yes-token-1",
        0.0,
        now - timedelta(hours=1),
        "official",
        False,
        True,
        False,
    )
    monkeypatch.setattr(
        "workflow_os.polymarket_paper_runner.fetch_gamma_market", lambda **_: resolved
    )
    monkeypatch.setattr(
        "workflow_os.polymarket_paper_runner.fetch_book",
        lambda *_: (_ for _ in ()).throw(AssertionError("resolved settlement must not use CLOB")),
    )
    monkeypatch.setattr(
        "workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: []
    )

    summary = run_paper_cycle(store=store, estimator=object(), now_utc=now)

    assert summary.exited == 1
    assert summary.held == 0
    assert store.open_count() == 0
    assert store.account().bankroll_usd == pytest.approx(expected_bankroll)


def test_runner_holds_ambiguous_closed_market(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    now = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
    store.open_yes(
        market_id="m1",
        stake_usd=3.0,
        entry_price=0.60,
        entry_fair_probability=0.75,
        opened_at=now - timedelta(days=1),
        yes_token_id="yes-token-1",
    )
    ambiguous = GammaMarket(
        "m1", "Question?", 0.5, "yes-token-1", 0.0,
        now - timedelta(hours=1), "official", False, True, False,
    )
    monkeypatch.setattr(
        "workflow_os.polymarket_paper_runner.fetch_gamma_market", lambda **_: ambiguous
    )
    monkeypatch.setattr(
        "workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: []
    )

    summary = run_paper_cycle(store=store, estimator=lambda _: None, now_utc=now)

    assert summary.exited == 0
    assert summary.held == 1
    assert store.open_count() == 1
    assert store.account().bankroll_usd == pytest.approx(47.0)
