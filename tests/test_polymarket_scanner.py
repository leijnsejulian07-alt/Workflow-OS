from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from workflow_os.polymarket_clob import BookLevel, ClobBook
from workflow_os.polymarket_gamma import GammaMarket
from workflow_os.polymarket_scanner import FairProbabilityEvidence, scan_paper_markets

NOW = datetime(2026, 9, 21, 17, 0, tzinfo=timezone.utc)
MARKET = GammaMarket(
    market_id="m1",
    question="Will the documented event happen?",
    yes_price=0.62,
    yes_token_id="yes-token",
    liquidity_usd=10_000.0,
    resolves_at=NOW + timedelta(hours=12),
    resolution_source="https://example.com/rules",
    active=True,
    closed=False,
    accepting_orders=True,
)
BOOK = ClobBook("yes-token", (), (BookLevel(0.62, 100.0),))


@patch("workflow_os.polymarket_scanner.fetch_book", return_value=BOOK)
@patch("workflow_os.polymarket_scanner.fetch_gamma_markets", return_value=[MARKET])
def test_scanner_reaches_guide_signal(fetch_markets, fetch_book):
    result = scan_paper_markets(
        estimator=lambda _: FairProbabilityEvidence(0.74, "model:test-fixture", NOW),
        bankroll_usd=50.0,
        open_positions=0,
        now_utc=NOW,
    )
    assert result[0].decision.action == "PAPER_BUY_YES"
    assert result[0].decision.stake_usd == 3.0
    assert result[0].evidence_source == "model:test-fixture"


@patch("workflow_os.polymarket_scanner.fetch_gamma_markets", return_value=[MARKET])
def test_missing_evidence_fails_closed_without_clob(fetch_markets):
    with patch("workflow_os.polymarket_scanner.fetch_book") as fetch_book:
        result = scan_paper_markets(estimator=lambda _: None, bankroll_usd=50.0, open_positions=0, now_utc=NOW)
    assert result[0].decision.reason == "MISSING_FAIR_VALUE_EVIDENCE"
    fetch_book.assert_not_called()


@patch("workflow_os.polymarket_scanner.fetch_gamma_markets", return_value=[MARKET])
def test_future_dated_evidence_fails_closed(fetch_markets):
    result = scan_paper_markets(
        estimator=lambda _: FairProbabilityEvidence(0.74, "future", NOW + timedelta(seconds=1)),
        bankroll_usd=50.0,
        open_positions=0,
        now_utc=NOW,
    )
    assert result[0].decision.reason == "MISSING_FAIR_VALUE_EVIDENCE"


@patch("workflow_os.polymarket_scanner.fetch_book", side_effect=RuntimeError("unavailable"))
@patch("workflow_os.polymarket_scanner.fetch_gamma_markets", return_value=[MARKET])
def test_clob_failure_fails_closed(fetch_markets, fetch_book):
    result = scan_paper_markets(
        estimator=lambda _: FairProbabilityEvidence(0.74, "model:test-fixture", NOW),
        bankroll_usd=50.0,
        open_positions=0,
        now_utc=NOW,
    )
    assert result[0].decision.reason == "CLOB_DATA_UNAVAILABLE"
