from datetime import datetime, timedelta, timezone

from workflow_os.polymarket_clob import BookLevel, ClobBook
from workflow_os.polymarket_gamma import GammaMarket
from workflow_os.polymarket_paper import PolymarketPaperDecision
from workflow_os.polymarket_paper_runner import run_paper_cycle
from workflow_os.polymarket_paper_state import PolymarketPaperStore
from workflow_os.polymarket_scanner import FairProbabilityEvidence, PaperScanResult


def test_runner_persists_valid_signal(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    signal = PaperScanResult(
        market_id="m1",
        question="Will test market resolve yes?",
        decision=PolymarketPaperDecision("PAPER_BUY_YES", "GUIDE_SIGNAL", 3.0, 12.0),
        market_price=0.62,
        fair_probability=0.74,
        yes_token_id="yes-token-1",
    )
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: [signal])

    summary = run_paper_cycle(
        store=store,
        estimator=object(),
        now_utc=datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc),
    )

    assert summary.opened == 1
    assert summary.held == 0
    assert summary.exited == 0
    assert store.open_count() == 1
    assert store.account().bankroll_usd == 47.0
    assert store.open_positions()[0].yes_token_id == "yes-token-1"


def test_runner_holds_signal_without_restart_safe_asset_identity(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    signal = PaperScanResult(
        market_id="m1",
        question="Will test market resolve yes?",
        decision=PolymarketPaperDecision("PAPER_BUY_YES", "GUIDE_SIGNAL", 3.0, 12.0),
        market_price=0.62,
        fair_probability=0.74,
        yes_token_id=None,
    )
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: [signal])

    summary = run_paper_cycle(
        store=store,
        estimator=object(),
        now_utc=datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc),
    )

    assert summary.opened == 0
    assert summary.held == 1
    assert store.open_count() == 0
    assert store.account().bankroll_usd == 50.0


def test_runner_holds_duplicate_without_crashing(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    store.open_yes(
        market_id="m1",
        stake_usd=3.0,
        entry_price=0.62,
        entry_fair_probability=0.74,
        opened_at=now,
        yes_token_id="yes-token-1",
    )
    signal = PaperScanResult(
        market_id="m1",
        question="Will test market resolve yes?",
        decision=PolymarketPaperDecision("PAPER_BUY_YES", "GUIDE_SIGNAL", 2.82, 12.0),
        market_price=0.62,
        fair_probability=0.74,
        yes_token_id="yes-token-1",
    )
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.fetch_gamma_market", lambda **_: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: [signal])

    summary = run_paper_cycle(store=store, estimator=object(), now_utc=now)

    assert summary.opened == 0
    assert summary.held == 2
    assert store.open_count() == 1
    assert store.account().bankroll_usd == 47.0


def test_runner_exits_against_full_bid_depth(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    store.open_yes(market_id="m1", stake_usd=3.0, entry_price=0.60, entry_fair_probability=0.75, opened_at=now - timedelta(hours=2), yes_token_id="yes-token-1")
    market = GammaMarket("m1", "Question?", 0.70, "yes-token-1", 10_000.0, now + timedelta(minutes=30), "official", True, False, True)
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.fetch_gamma_market", lambda **_: market)
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.fetch_book", lambda *_: ClobBook("yes-token-1", (BookLevel(0.68, 10.0),), ()))
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: [])
    estimator = lambda _: FairProbabilityEvidence(0.76, "test", now)

    summary = run_paper_cycle(store=store, estimator=estimator, now_utc=now)

    assert summary.exited == 1
    assert store.open_count() == 0
    assert store.account().bankroll_usd == 50.4


def test_runner_never_invents_exit_when_bid_depth_is_insufficient(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db", starting_bankroll_usd=50.0)
    now = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    store.open_yes(market_id="m1", stake_usd=3.0, entry_price=0.60, entry_fair_probability=0.75, opened_at=now - timedelta(hours=2), yes_token_id="yes-token-1")
    market = GammaMarket("m1", "Question?", 0.70, "yes-token-1", 10_000.0, now + timedelta(minutes=30), "official", True, False, True)
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.fetch_gamma_market", lambda **_: market)
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.fetch_book", lambda *_: ClobBook("yes-token-1", (BookLevel(0.68, 1.0),), ()))
    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", lambda **_: [])
    estimator = lambda _: FairProbabilityEvidence(0.76, "test", now)

    summary = run_paper_cycle(store=store, estimator=estimator, now_utc=now)

    assert summary.exited == 0
    assert summary.held == 1
    assert store.open_count() == 1
    assert store.account().bankroll_usd == 47.0


def test_runner_never_scans_stopped_account(monkeypatch, tmp_path):
    store = PolymarketPaperStore(tmp_path / "paper.db")
    store.stop("TEST_STOP")

    def forbidden(**_):
        raise AssertionError("scanner must not run after stop")

    monkeypatch.setattr("workflow_os.polymarket_paper_runner.scan_paper_markets", forbidden)
    summary = run_paper_cycle(store=store, estimator=object())

    assert summary.stopped is True
    assert summary.stop_reason == "TEST_STOP"
    assert summary.scanned == 0
