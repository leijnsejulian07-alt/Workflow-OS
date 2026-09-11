from decimal import Decimal

from tests import unittest_compat as pytest

from workflow_os.alpaca_paper_equity import AlpacaPaperEquityCurve, AlpacaPaperEquityPoint
from workflow_os.alpaca_paper_funded_readiness import (
    AlpacaPaperValidationWindow,
    evaluate_alpaca_funded_readiness,
)
from workflow_os.alpaca_paper_learning_adapter import AlpacaPaperLearningContext
from workflow_os.trading_paper_learning import PaperLearningPolicy


FINGERPRINT = "a" * 64


def _curve(*, occurred_at: str, pnl: str = "10", fingerprint: str = FINGERPRINT) -> AlpacaPaperEquityCurve:
    pnl_value = Decimal(pnl)
    starting = Decimal("1000")
    ending = starting + pnl_value
    drawdown = Decimal("0") if pnl_value >= 0 else -pnl_value / starting * Decimal("100")
    point = AlpacaPaperEquityPoint(
        occurred_at=occurred_at,
        symbol="AAPL",
        opening_client_order_id=f"open-{occurred_at}",
        closing_client_order_id=f"close-{occurred_at}",
        paper_realized_pnl_usd=pnl_value,
        cumulative_pnl_usd=pnl_value,
        equity_usd=ending,
        drawdown_pct=drawdown,
    )
    return AlpacaPaperEquityCurve(
        strategy_id="alpha",
        strategy_policy_fingerprint=fingerprint,
        starting_equity_usd=starting,
        ending_equity_usd=ending,
        net_paper_pnl_usd=pnl_value,
        modeled_execution_costs_usd=Decimal("1"),
        max_drawdown_pct=drawdown,
        trade_count=1,
        points=(point,),
    )


def _context(*, start: str, end: str, observed: str, version: str = "v1") -> AlpacaPaperLearningContext:
    return AlpacaPaperLearningContext(
        strategy_family="momentum",
        strategy_version=version,
        validation_start=start,
        validation_end=end,
        execution_error_count=0,
        ambiguous_side_effect_count=0,
        market_regimes=("trend", "range"),
        observed_at=observed,
    )


def _window(*, train_start: str, train_end: str, start: str, end: str, occurred_at: str, pnl: str = "10", fingerprint: str = FINGERPRINT, version: str = "v1") -> AlpacaPaperValidationWindow:
    return AlpacaPaperValidationWindow(
        curve=_curve(occurred_at=occurred_at, pnl=pnl, fingerprint=fingerprint),
        context=_context(start=start, end=end, observed=end, version=version),
        train_start=train_start,
        train_end=train_end,
    )


def _policy() -> PaperLearningPolicy:
    return PaperLearningPolicy(
        min_validation_trades=1,
        min_validation_days=1,
        min_market_regimes=2,
        max_drawdown_pct=8.0,
        max_execution_error_rate=0.02,
        min_green_windows_for_funded_ready=2,
        min_total_oos_days_for_funded_ready=2,
    )


def test_sustained_non_overlapping_execution_derived_windows_reach_evidence_only_funded_ready() -> None:
    windows = (
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-10T12:00:00Z",
        ),
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-11T00:00:00Z",
            start="2026-08-11T00:00:00Z",
            end="2026-08-12T00:00:00Z",
            occurred_at="2026-08-11T12:00:00Z",
        ),
    )

    decision = evaluate_alpaca_funded_readiness(windows, _policy())

    assert decision.state == "FUNDED_READY"
    assert len(decision.qualifying_window_fingerprints) == 2
    assert decision.may_purchase_funded_account is False
    assert decision.may_request_live_credentials is False
    assert decision.may_enter_live_execution is False


def test_validation_window_rejects_equity_points_outside_oos_interval() -> None:
    with pytest.raises(ValueError, match="outside its validation window"):
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-11T00:00:00Z",
        )


def test_overlapping_oos_windows_do_not_reach_funded_ready() -> None:
    windows = (
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-12T00:00:00Z",
            occurred_at="2026-08-10T12:00:00Z",
        ),
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-11T00:00:00Z",
            start="2026-08-11T00:00:00Z",
            end="2026-08-13T00:00:00Z",
            occurred_at="2026-08-11T12:00:00Z",
        ),
    )

    decision = evaluate_alpaca_funded_readiness(windows, _policy())

    assert decision.state == "PAPER_AMBER"
    assert decision.reasons == ("QUALIFYING_OOS_WINDOWS_OVERLAP",)


def test_exact_strategy_policy_fingerprint_must_remain_stable() -> None:
    windows = (
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-10T12:00:00Z",
        ),
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-11T00:00:00Z",
            start="2026-08-11T00:00:00Z",
            end="2026-08-12T00:00:00Z",
            occurred_at="2026-08-11T12:00:00Z",
            fingerprint="b" * 64,
        ),
    )

    decision = evaluate_alpaca_funded_readiness(windows, _policy())

    assert decision.state == "PAPER_AMBER"
    assert decision.reasons == ("GREEN_WINDOWS_NOT_FROM_ONE_EXACT_STRATEGY_POLICY",)


def test_strategy_version_must_remain_stable_across_qualifying_windows() -> None:
    windows = (
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-10T12:00:00Z",
        ),
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-11T00:00:00Z",
            start="2026-08-11T00:00:00Z",
            end="2026-08-12T00:00:00Z",
            occurred_at="2026-08-11T12:00:00Z",
            version="v2",
        ),
    )

    decision = evaluate_alpaca_funded_readiness(windows, _policy())

    assert decision.state == "PAPER_AMBER"
    assert decision.reasons == ("GREEN_WINDOWS_NOT_FROM_ONE_STABLE_STRATEGY_VERSION",)


def test_red_execution_derived_window_blocks_readiness() -> None:
    windows = (
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-10T12:00:00Z",
            pnl="-10",
        ),
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-11T00:00:00Z",
            start="2026-08-11T00:00:00Z",
            end="2026-08-12T00:00:00Z",
            occurred_at="2026-08-11T12:00:00Z",
        ),
    )

    decision = evaluate_alpaca_funded_readiness(windows, _policy())

    assert decision.state == "PAPER_RED"
    assert "NON_POSITIVE_NET_PAPER_PNL" in decision.reasons


def test_training_and_validation_windows_may_not_overlap() -> None:
    with pytest.raises(ValueError, match="chronological and non-overlapping"):
        _window(
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T12:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            occurred_at="2026-08-10T13:00:00Z",
        )

load_tests = pytest.make_load_tests(globals())
