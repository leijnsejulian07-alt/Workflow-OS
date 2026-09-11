from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable

from .alpaca_market_data import AlpacaLatestBarObservation, fetch_latest_iex_bar
from .alpaca_paper_transport import (
    AlpacaPaperCredentials,
    AlpacaPaperOrder,
    _HttpResult,
    _default_request,
    reconcile_paper_order,
    submit_paper_order,
)
from .side_effects import SideEffectLedger, SideEffectRecord
from .trading_order_execution import execute_reserved_trading_order, reconcile_unknown_trading_order
from .trading_order_reservation import TradingOrderReservationResult
from .trading_order_risk_gate import TradingOrderRiskDecision

ALPACA_PAPER_RUNTIME_POLICY_VERSION = "alpaca-paper-runtime/1"
ALPACA_PAPER_ACTION = "ALPACA_PAPER_ORDER"


@dataclass(frozen=True)
class AlpacaPaperStrategyPolicy:
    strategy_id: str
    quantity_shares: float = 0.01
    minimum_body_bps: float = 5.0
    maximum_bar_range_bps: float = 150.0
    maximum_order_notional_usd: float = 25.0

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, str) or not self.strategy_id.strip() or len(self.strategy_id) > 100:
            raise ValueError("strategy_id is required and bounded")
        for name, value in (
            ("quantity_shares", self.quantity_shares),
            ("minimum_body_bps", self.minimum_body_bps),
            ("maximum_bar_range_bps", self.maximum_bar_range_bps),
            ("maximum_order_notional_usd", self.maximum_order_notional_usd),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class AlpacaPaperDecision:
    action: str
    reason: str
    client_order_id: str | None = None
    order: AlpacaPaperOrder | None = None


@dataclass(frozen=True)
class AlpacaPaperRuntimeResult:
    status: str
    observation: AlpacaLatestBarObservation | None
    decision: AlpacaPaperDecision | None
    side_effect: SideEffectRecord | None


def _client_order_id(*, policy: AlpacaPaperStrategyPolicy, observation: AlpacaLatestBarObservation) -> str:
    raw = f"{ALPACA_PAPER_RUNTIME_POLICY_VERSION}|{policy.strategy_id}|{observation.symbol}|{observation.timestamp}".encode("utf-8")
    return f"wfos-paper-{hashlib.sha256(raw).hexdigest()[:32]}"


def evaluate_paper_observation(
    *, observation: AlpacaLatestBarObservation, policy: AlpacaPaperStrategyPolicy
) -> AlpacaPaperDecision:
    """Deterministic, deliberately simple paper-only candidate strategy.

    This is learning instrumentation, not a profitability claim. V1 permits only a
    small long BUY when the verified minute bar closes sufficiently above its open,
    the close is not below VWAP, the bar has trades, and bounded volatility/notional
    gates pass. Every other case fails closed to HOLD. Short selling is unreachable.
    """

    if not isinstance(observation, AlpacaLatestBarObservation):
        raise ValueError("observation must be a validated AlpacaLatestBarObservation")
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise ValueError("policy must be a validated AlpacaPaperStrategyPolicy")
    if observation.feed != "iex":
        return AlpacaPaperDecision("HOLD", "UNAPPROVED_MARKET_DATA_FEED")
    if observation.volume <= 0 or observation.trade_count <= 0:
        return AlpacaPaperDecision("HOLD", "INSUFFICIENT_MARKET_ACTIVITY")

    body_bps = ((observation.close - observation.open) / observation.open) * 10_000.0
    range_bps = ((observation.high - observation.low) / observation.open) * 10_000.0
    if not math.isfinite(body_bps) or not math.isfinite(range_bps):
        return AlpacaPaperDecision("HOLD", "INVALID_DERIVED_MARKET_FEATURE")
    if range_bps > policy.maximum_bar_range_bps:
        return AlpacaPaperDecision("HOLD", "BAR_RANGE_RISK_LIMIT")
    if body_bps < policy.minimum_body_bps or observation.close < observation.vwap:
        return AlpacaPaperDecision("HOLD", "NO_LONG_SIGNAL")

    notional = observation.close * policy.quantity_shares
    if not math.isfinite(notional) or notional > policy.maximum_order_notional_usd:
        return AlpacaPaperDecision("HOLD", "ORDER_NOTIONAL_RISK_LIMIT")

    client_order_id = _client_order_id(policy=policy, observation=observation)
    order = AlpacaPaperOrder(
        client_order_id=client_order_id,
        symbol=observation.symbol,
        qty=format(policy.quantity_shares, ".12g"),
        side="buy",
    )
    return AlpacaPaperDecision("BUY", "DETERMINISTIC_LONG_SIGNAL", client_order_id, order)


def _reservation(
    *, ledger: SideEffectLedger, account_id: str, observation: AlpacaLatestBarObservation,
    policy: AlpacaPaperStrategyPolicy, decision: AlpacaPaperDecision,
) -> TradingOrderReservationResult:
    if decision.action != "BUY" or decision.order is None or decision.client_order_id is None:
        raise RuntimeError("only an approved paper BUY may be reserved")
    if not isinstance(account_id, str) or not account_id.strip() or account_id != account_id.strip() or len(account_id) > 200:
        raise ValueError("paper account_id is required, canonical and bounded")
    risk = TradingOrderRiskDecision(
        "PASS_TO_SIDE_EFFECT_RESERVATION", (), True, ALPACA_PAPER_RUNTIME_POLICY_VERSION
    )
    reservation = ledger.reserve(
        idempotency_key=decision.client_order_id,
        action=ALPACA_PAPER_ACTION,
        target=f"ALPACA_PAPER:{account_id}",
        payload={
            "mode": "PAPER_ONLY",
            "strategy_id": policy.strategy_id,
            "policy_version": ALPACA_PAPER_RUNTIME_POLICY_VERSION,
            "symbol": observation.symbol,
            "observation_timestamp": observation.timestamp,
            "observation_close": observation.close,
            "side": "BUY",
            "quantity_shares": policy.quantity_shares,
            "maximum_order_notional_usd": policy.maximum_order_notional_usd,
        },
        max_attempts=2,
    )
    return TradingOrderReservationResult(risk, reservation)


def run_alpaca_paper_once(
    *, credentials: AlpacaPaperCredentials, account_id: str, symbol: str,
    ledger: SideEffectLedger, policy: AlpacaPaperStrategyPolicy,
    market_request_fn: Callable = _default_request, order_request_fn: Callable = _default_request,
    timeout_seconds: float = 10.0,
) -> AlpacaPaperRuntimeResult:
    """Fetch one real observation and drive at most one idempotent Alpaca PAPER order.

    Existing UNKNOWN effects are reconciled before any retry. SUCCEEDED effects are
    returned as-is. No code path accepts a live Alpaca base URL or live credentials.
    """

    observation = fetch_latest_iex_bar(
        credentials=credentials, symbol=symbol, timeout_seconds=timeout_seconds,
        request_fn=market_request_fn,
    )
    if observation is None:
        return AlpacaPaperRuntimeResult("NO_OBSERVATION", None, None, None)

    decision = evaluate_paper_observation(observation=observation, policy=policy)
    if decision.action == "HOLD":
        return AlpacaPaperRuntimeResult("HOLD", observation, decision, None)

    assert decision.client_order_id is not None and decision.order is not None
    current = ledger.get(decision.client_order_id)
    if current is not None and current.state == "SUCCEEDED":
        return AlpacaPaperRuntimeResult("ALREADY_SUCCEEDED", observation, decision, current)
    if current is not None and current.state == "UNKNOWN":
        reconciled = reconcile_unknown_trading_order(
            ledger=ledger,
            idempotency_key=decision.client_order_id,
            reconcile=lambda: reconcile_paper_order(
                credentials=credentials, client_order_id=decision.client_order_id,
                timeout_seconds=timeout_seconds, request_fn=order_request_fn,
            ),
        )
        return AlpacaPaperRuntimeResult(
            "RECONCILED" if reconciled.state == "SUCCEEDED" else "RECONCILE_REQUIRED",
            observation, decision, reconciled,
        )
    if current is not None and current.state == "EXECUTING":
        return AlpacaPaperRuntimeResult("RECONCILE_REQUIRED", observation, decision, current)

    reservation = _reservation(
        ledger=ledger, account_id=account_id, observation=observation,
        policy=policy, decision=decision,
    )
    effect = execute_reserved_trading_order(
        reservation,
        ledger=ledger,
        submit=lambda: submit_paper_order(
            credentials=credentials, order=decision.order,
            timeout_seconds=timeout_seconds, request_fn=order_request_fn,
        ),
    )
    return AlpacaPaperRuntimeResult("EXECUTED", observation, decision, effect)
