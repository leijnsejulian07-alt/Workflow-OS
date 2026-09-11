from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .alpaca_market_data import AlpacaLatestBarObservation, fetch_latest_iex_bar
from .alpaca_paper_transport import (
    AlpacaPaperCredentials,
    AlpacaPaperOrder,
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
    maximum_observation_age_seconds: float = 180.0
    maximum_future_skew_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.strategy_id, str)
            or not self.strategy_id.strip()
            or self.strategy_id != self.strategy_id.strip()
            or len(self.strategy_id) > 100
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in self.strategy_id)
        ):
            raise ValueError("strategy_id is required, canonical and bounded")
        for name, value in (
            ("quantity_shares", self.quantity_shares),
            ("minimum_body_bps", self.minimum_body_bps),
            ("maximum_bar_range_bps", self.maximum_bar_range_bps),
            ("maximum_order_notional_usd", self.maximum_order_notional_usd),
            ("maximum_observation_age_seconds", self.maximum_observation_age_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        future_skew = self.maximum_future_skew_seconds
        if (
            isinstance(future_skew, bool)
            or not isinstance(future_skew, (int, float))
            or not math.isfinite(float(future_skew))
            or float(future_skew) < 0
        ):
            raise ValueError("maximum_future_skew_seconds must be finite and nonnegative")


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


def _validated_account_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 200
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ValueError("paper account_id is required, canonical and bounded")
    return value


def _target(account_id: str) -> str:
    return f"ALPACA_PAPER:{_validated_account_id(account_id)}"


def _strategy_policy_fingerprint(policy: AlpacaPaperStrategyPolicy) -> str:
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise ValueError("policy must be a validated AlpacaPaperStrategyPolicy")
    canonical = "|".join(
        (
            ALPACA_PAPER_RUNTIME_POLICY_VERSION,
            policy.strategy_id,
            format(float(policy.quantity_shares), ".17g"),
            format(float(policy.minimum_body_bps), ".17g"),
            format(float(policy.maximum_bar_range_bps), ".17g"),
            format(float(policy.maximum_order_notional_usd), ".17g"),
            format(float(policy.maximum_observation_age_seconds), ".17g"),
            format(float(policy.maximum_future_skew_seconds), ".17g"),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _client_order_id(*, policy: AlpacaPaperStrategyPolicy, observation: AlpacaLatestBarObservation) -> str:
    policy_fingerprint = _strategy_policy_fingerprint(policy)
    raw = f"{policy_fingerprint}|{observation.symbol}|{observation.timestamp}".encode("utf-8")
    return f"wfos-paper-{hashlib.sha256(raw).hexdigest()[:32]}"


def _utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _observation_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00") if value.endswith("Z") else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_paper_observation(
    *,
    observation: AlpacaLatestBarObservation,
    policy: AlpacaPaperStrategyPolicy,
    now_utc: datetime | None = None,
) -> AlpacaPaperDecision:
    """Deterministic, deliberately simple paper-only candidate strategy.

    This is learning instrumentation, not a profitability claim. V1 permits only a
    small long BUY when the verified minute bar is fresh, closes sufficiently above
    its open, is not below VWAP, has trades, and bounded volatility/notional gates
    pass. Every other case fails closed to HOLD. Short selling is unreachable.
    """

    if not isinstance(observation, AlpacaLatestBarObservation):
        raise ValueError("observation must be a validated AlpacaLatestBarObservation")
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise ValueError("policy must be a validated AlpacaPaperStrategyPolicy")
    if observation.feed != "iex":
        return AlpacaPaperDecision("HOLD", "UNAPPROVED_MARKET_DATA_FEED")

    observed_at = _observation_datetime(observation.timestamp)
    if observed_at is None:
        return AlpacaPaperDecision("HOLD", "INVALID_OBSERVATION_TIMESTAMP")
    age_seconds = (_utc_datetime(now_utc) - observed_at).total_seconds()
    if age_seconds > policy.maximum_observation_age_seconds:
        return AlpacaPaperDecision("HOLD", "STALE_MARKET_OBSERVATION")
    if age_seconds < -policy.maximum_future_skew_seconds:
        return AlpacaPaperDecision("HOLD", "FUTURE_MARKET_OBSERVATION")

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
    target = _target(account_id)
    policy_fingerprint = _strategy_policy_fingerprint(policy)
    risk = TradingOrderRiskDecision(
        "PASS_TO_SIDE_EFFECT_RESERVATION", (), True, ALPACA_PAPER_RUNTIME_POLICY_VERSION
    )
    reservation = ledger.reserve(
        idempotency_key=decision.client_order_id,
        action=ALPACA_PAPER_ACTION,
        target=target,
        payload={
            "mode": "PAPER_ONLY",
            "strategy_id": policy.strategy_id,
            "strategy_policy_fingerprint": policy_fingerprint,
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
    timeout_seconds: float = 10.0, now_utc: datetime | None = None,
) -> AlpacaPaperRuntimeResult:
    """Fetch one real observation and drive at most one idempotent Alpaca PAPER order.

    Existing UNKNOWN effects are reconciled before any retry. SUCCEEDED effects are
    returned as-is only after the immutable action/target/payload binding is verified.
    No code path accepts a live Alpaca base URL or live credentials. Stale or materially
    future-dated market observations fail closed before reservation.
    """

    _target(account_id)
    observation = fetch_latest_iex_bar(
        credentials=credentials, symbol=symbol, timeout_seconds=timeout_seconds,
        request_fn=market_request_fn,
    )
    if observation is None:
        return AlpacaPaperRuntimeResult("NO_OBSERVATION", None, None, None)

    decision = evaluate_paper_observation(observation=observation, policy=policy, now_utc=now_utc)
    if decision.action == "HOLD":
        return AlpacaPaperRuntimeResult("HOLD", observation, decision, None)

    assert decision.client_order_id is not None and decision.order is not None
    reservation = _reservation(
        ledger=ledger, account_id=account_id, observation=observation,
        policy=policy, decision=decision,
    )
    current = reservation.reservation
    if current.state == "SUCCEEDED":
        return AlpacaPaperRuntimeResult("ALREADY_SUCCEEDED", observation, decision, current)
    if current.state == "UNKNOWN":
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
    if current.state == "EXECUTING":
        return AlpacaPaperRuntimeResult("RECONCILE_REQUIRED", observation, decision, current)

    effect = execute_reserved_trading_order(
        reservation,
        ledger=ledger,
        submit=lambda: submit_paper_order(
            credentials=credentials, order=decision.order,
            timeout_seconds=timeout_seconds, request_fn=order_request_fn,
        ),
    )
    return AlpacaPaperRuntimeResult("EXECUTED", observation, decision, effect)
