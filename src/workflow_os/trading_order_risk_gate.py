from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

TRADING_ORDER_RISK_POLICY_VERSION = "trading-order-risk/1"


def _positive(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _nonnegative(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def _text(value: object, name: str, limit: int = 128) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required")
    text = value.strip().upper()
    if not text or len(text) > limit:
        raise ValueError(f"{name} is required and bounded")
    return text


@dataclass(frozen=True)
class TradingRiskSnapshot:
    account_id: str
    provider: str
    program: str
    daily_loss_limit: float
    max_drawdown: float
    max_position_contracts: float
    realized_daily_loss: float
    current_drawdown: float
    open_position_contracts: float
    account_health: str
    emergency_kill_switch: bool
    rules_fresh: bool
    reconciliation_healthy: bool
    production_enabled: bool


@dataclass(frozen=True)
class TradingOrderIntent:
    idempotency_key: str
    account_id: str
    symbol: str
    side: str
    quantity_contracts: float
    max_loss_if_filled: float


@dataclass(frozen=True)
class TradingOrderRiskDecision:
    decision: str
    reasons: tuple[str, ...]
    may_reserve_side_effect: bool
    policy_version: str = TRADING_ORDER_RISK_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def evaluate_trading_order_risk(
    *, snapshot: TradingRiskSnapshot, intent: TradingOrderIntent
) -> TradingOrderRiskDecision:
    """Fail-closed pre-side-effect gate for a future funded-account order adapter.

    This function never calls a broker and never grants execution authority. A PASS
    only means the intent may be reserved in the shared SideEffectLedger; the
    external adapter must still enforce provider/account and idempotency controls.
    """

    if _text(intent.account_id, "intent.account_id", 200) != _text(snapshot.account_id, "snapshot.account_id", 200):
        return TradingOrderRiskDecision("HOLD", ("ACCOUNT_IDENTITY_MISMATCH",), False)
    _text(snapshot.provider, "provider")
    _text(snapshot.program, "program")
    _text(intent.idempotency_key, "idempotency_key", 200)
    _text(intent.symbol, "symbol", 64)
    side = _text(intent.side, "side", 8)
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")

    quantity = _positive(intent.quantity_contracts, "quantity_contracts")
    order_max_loss = _positive(intent.max_loss_if_filled, "max_loss_if_filled")
    daily_limit = _positive(snapshot.daily_loss_limit, "daily_loss_limit")
    drawdown_limit = _positive(snapshot.max_drawdown, "max_drawdown")
    position_limit = _positive(snapshot.max_position_contracts, "max_position_contracts")
    daily_loss = _nonnegative(snapshot.realized_daily_loss, "realized_daily_loss")
    drawdown = _nonnegative(snapshot.current_drawdown, "current_drawdown")
    open_contracts = _nonnegative(snapshot.open_position_contracts, "open_position_contracts")

    reasons: list[str] = []
    if snapshot.emergency_kill_switch:
        reasons.append("EMERGENCY_KILL_SWITCH_ACTIVE")
    if snapshot.account_health != "HEALTHY":
        reasons.append("ACCOUNT_NOT_HEALTHY")
    if not snapshot.rules_fresh:
        reasons.append("PROVIDER_RULES_STALE_OR_UNKNOWN")
    if not snapshot.reconciliation_healthy:
        reasons.append("RECONCILIATION_UNHEALTHY")
    if not snapshot.production_enabled:
        reasons.append("LIVE_TRADING_NOT_EXPLICITLY_ENABLED")
    if daily_loss >= daily_limit or daily_loss + order_max_loss > daily_limit:
        reasons.append("DAILY_LOSS_LIMIT_WOULD_BE_BREACHED")
    if drawdown >= drawdown_limit or drawdown + order_max_loss > drawdown_limit:
        reasons.append("MAX_DRAWDOWN_WOULD_BE_BREACHED")
    if open_contracts + quantity > position_limit:
        reasons.append("POSITION_LIMIT_WOULD_BE_BREACHED")

    if reasons:
        return TradingOrderRiskDecision("HOLD", tuple(reasons), False)
    return TradingOrderRiskDecision("PASS_TO_SIDE_EFFECT_RESERVATION", (), True)
