from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .alpaca_paper_equity import AlpacaPaperEquityCurve
from .trading_paper_learning import (
    PAPER_LEARNING_POLICY_VERSION,
    PaperLearningDecision,
    PaperLearningPolicy,
)

ALPACA_PAPER_LEARNING_ADAPTER_POLICY_VERSION = "alpaca-paper-learning-adapter/1"
_MAX_TEXT = 128
_MAX_REGIMES = 16
_MAX_REGIME_TEXT = 64


def _bounded_text(value: object, *, field: str, max_chars: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_chars:
        raise ValueError(f"{field} is required and bounded")
    return cleaned


def _utc(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _finite_decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a lowercase sha256 digest") from exc
    return value


@dataclass(frozen=True)
class AlpacaPaperLearningContext:
    strategy_family: str
    strategy_version: str
    validation_start: str
    validation_end: str
    execution_error_count: int
    ambiguous_side_effect_count: int
    market_regimes: tuple[str, ...]
    observed_at: str
    policy_version: str = ALPACA_PAPER_LEARNING_ADAPTER_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != ALPACA_PAPER_LEARNING_ADAPTER_POLICY_VERSION:
            raise ValueError("alpaca paper learning adapter policy version mismatch")
        object.__setattr__(self, "strategy_family", _bounded_text(self.strategy_family, field="strategy_family"))
        object.__setattr__(self, "strategy_version", _bounded_text(self.strategy_version, field="strategy_version"))
        start = _utc(self.validation_start, field="validation_start")
        end = _utc(self.validation_end, field="validation_end")
        observed = _utc(self.observed_at, field="observed_at")
        if not start < end:
            raise ValueError("validation window must be chronological")
        if observed < end:
            raise ValueError("observed_at may not predate validation_end")
        for field in ("execution_error_count", "ambiguous_side_effect_count"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field} is invalid")
        if not isinstance(self.market_regimes, tuple) or not 1 <= len(self.market_regimes) <= _MAX_REGIMES:
            raise ValueError("market_regimes are invalid")
        normalized: list[str] = []
        for regime in self.market_regimes:
            value = _bounded_text(regime, field="market_regime", max_chars=_MAX_REGIME_TEXT).lower()
            normalized.append(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("market_regimes must be unique")
        object.__setattr__(self, "market_regimes", tuple(normalized))

    @property
    def validation_days(self) -> int:
        return max(
            0,
            (
                _utc(self.validation_end, field="validation_end")
                - _utc(self.validation_start, field="validation_start")
            ).days,
        )


def _validate_curve(curve: AlpacaPaperEquityCurve) -> tuple[Decimal, Decimal]:
    _bounded_text(curve.strategy_id, field="strategy_id")
    _sha256(curve.strategy_policy_fingerprint, field="strategy_policy_fingerprint")
    if curve.proves_received_cash is not False:
        raise ValueError("paper equity may not prove received cash")
    if curve.proves_realized_cash_pnl is not False:
        raise ValueError("paper equity may not prove realized cash pnl")
    if curve.may_enter_live_execution is not False:
        raise ValueError("paper equity may not grant live execution")
    if not isinstance(curve.trade_count, int) or isinstance(curve.trade_count, bool) or curve.trade_count < 0:
        raise ValueError("paper equity trade count is invalid")
    if curve.trade_count != len(curve.points):
        raise ValueError("paper equity trade count is inconsistent")

    starting = _finite_decimal(curve.starting_equity_usd, field="starting_equity_usd")
    ending = _finite_decimal(curve.ending_equity_usd, field="ending_equity_usd")
    net_pnl = _finite_decimal(curve.net_paper_pnl_usd, field="net_paper_pnl_usd")
    costs = _finite_decimal(curve.modeled_execution_costs_usd, field="modeled_execution_costs_usd")
    drawdown = _finite_decimal(curve.max_drawdown_pct, field="max_drawdown_pct")
    if starting <= 0:
        raise ValueError("starting_equity_usd must be positive")
    if costs < 0:
        raise ValueError("modeled_execution_costs_usd must be nonnegative")
    if ending != starting + net_pnl:
        raise ValueError("paper equity ending balance is inconsistent")
    if drawdown < 0 or drawdown > 100:
        raise ValueError("max_drawdown_pct must be between 0 and 100")

    cumulative = Decimal("0")
    peak = starting
    recomputed_max_drawdown = Decimal("0")
    previous_time: datetime | None = None
    seen_pairs: set[tuple[str, str]] = set()
    for point in curve.points:
        occurred = _utc(point.occurred_at, field="equity_point.occurred_at")
        if previous_time is not None and occurred <= previous_time:
            raise ValueError("paper equity points must be strictly chronological")
        previous_time = occurred
        opening_id = _bounded_text(point.opening_client_order_id, field="opening_client_order_id")
        closing_id = _bounded_text(point.closing_client_order_id, field="closing_client_order_id")
        if opening_id == closing_id:
            raise ValueError("paper equity order pair is invalid")
        pair = (opening_id, closing_id)
        if pair in seen_pairs:
            raise ValueError("paper equity order pair is duplicated")
        seen_pairs.add(pair)
        _bounded_text(point.symbol, field="symbol")
        pnl = _finite_decimal(point.paper_realized_pnl_usd, field="point.paper_realized_pnl_usd")
        cumulative += pnl
        point_cumulative = _finite_decimal(point.cumulative_pnl_usd, field="point.cumulative_pnl_usd")
        point_equity = _finite_decimal(point.equity_usd, field="point.equity_usd")
        point_drawdown = _finite_decimal(point.drawdown_pct, field="point.drawdown_pct")
        if point_cumulative != cumulative:
            raise ValueError("paper equity cumulative pnl is inconsistent")
        if point_equity != starting + cumulative:
            raise ValueError("paper equity point balance is inconsistent")
        if point_equity > peak:
            peak = point_equity
        expected_drawdown = Decimal("100") if point_equity <= 0 else (peak - point_equity) / peak * Decimal("100")
        if point_drawdown != expected_drawdown:
            raise ValueError("paper equity point drawdown is inconsistent")
        if point_drawdown > recomputed_max_drawdown:
            recomputed_max_drawdown = point_drawdown

    if cumulative != net_pnl:
        raise ValueError("paper equity net pnl is inconsistent")
    if recomputed_max_drawdown != drawdown:
        raise ValueError("paper equity max drawdown is inconsistent")
    return net_pnl, drawdown


def _curve_fingerprint(curve: AlpacaPaperEquityCurve, context: AlpacaPaperLearningContext) -> str:
    payload = {
        "adapter_policy_version": ALPACA_PAPER_LEARNING_ADAPTER_POLICY_VERSION,
        "equity_policy_version": curve.policy_version,
        "strategy_id": curve.strategy_id,
        "strategy_policy_fingerprint": curve.strategy_policy_fingerprint,
        "starting_equity_usd": str(curve.starting_equity_usd),
        "ending_equity_usd": str(curve.ending_equity_usd),
        "net_paper_pnl_usd": str(curve.net_paper_pnl_usd),
        "modeled_execution_costs_usd": str(curve.modeled_execution_costs_usd),
        "max_drawdown_pct": str(curve.max_drawdown_pct),
        "trade_count": curve.trade_count,
        "position_order_pairs": [
            [point.opening_client_order_id, point.closing_client_order_id]
            for point in curve.points
        ],
        "strategy_family": context.strategy_family,
        "strategy_version": context.strategy_version,
        "validation_start": _utc(context.validation_start, field="validation_start").isoformat(),
        "validation_end": _utc(context.validation_end, field="validation_end").isoformat(),
        "execution_error_count": context.execution_error_count,
        "ambiguous_side_effect_count": context.ambiguous_side_effect_count,
        "market_regimes": list(context.market_regimes),
        "observed_at": _utc(context.observed_at, field="observed_at").isoformat(),
    }
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def evaluate_alpaca_paper_equity_curve(
    *,
    curve: AlpacaPaperEquityCurve,
    context: AlpacaPaperLearningContext,
    policy: PaperLearningPolicy | None = None,
) -> PaperLearningDecision:
    """Evaluate execution-derived Alpaca paper results without inventing FX conversion.

    Paper-learning policy v1 only uses the sign of net P&L, not its EUR magnitude.
    Therefore USD paper P&L can be evaluated directly for positive/non-positive
    performance while drawdown remains currency-independent. This adapter is pinned
    to policy v1 and must be revised before any future policy introduces monetary
    thresholds.
    """
    if not isinstance(curve, AlpacaPaperEquityCurve):
        raise TypeError("curve must be AlpacaPaperEquityCurve")
    if not isinstance(context, AlpacaPaperLearningContext):
        raise TypeError("context must be AlpacaPaperLearningContext")
    policy = policy or PaperLearningPolicy()
    if policy.policy_version != PAPER_LEARNING_POLICY_VERSION:
        raise ValueError("unsupported paper learning policy version")
    net_pnl, drawdown = _validate_curve(curve)

    fingerprint = _curve_fingerprint(curve, context)
    hard_failures: list[str] = []
    if context.ambiguous_side_effect_count:
        hard_failures.append("UNRESOLVED_AMBIGUOUS_SIDE_EFFECTS")
    if net_pnl <= 0:
        hard_failures.append("NON_POSITIVE_NET_PAPER_PNL")
    if drawdown > Decimal(str(policy.max_drawdown_pct)):
        hard_failures.append("PAPER_DRAWDOWN_TOO_HIGH")
    denominator = max(1, curve.trade_count + context.execution_error_count)
    execution_error_rate = context.execution_error_count / denominator
    if execution_error_rate > policy.max_execution_error_rate:
        hard_failures.append("EXECUTION_ERROR_RATE_TOO_HIGH")
    if hard_failures:
        return PaperLearningDecision(
            strategy_id=curve.strategy_id,
            strategy_family=context.strategy_family,
            strategy_version=context.strategy_version,
            state="PAPER_RED",
            action="PAUSE_OR_REPLACE_STRATEGY",
            reasons=tuple(hard_failures),
            window_fingerprint=fingerprint,
        )

    reasons: list[str] = []
    if curve.trade_count < policy.min_validation_trades:
        reasons.append("INSUFFICIENT_OOS_TRADES")
    if context.validation_days < policy.min_validation_days:
        reasons.append("INSUFFICIENT_OOS_DURATION")
    if len(context.market_regimes) < policy.min_market_regimes:
        reasons.append("INSUFFICIENT_MARKET_REGIME_COVERAGE")
    if reasons:
        return PaperLearningDecision(
            strategy_id=curve.strategy_id,
            strategy_family=context.strategy_family,
            strategy_version=context.strategy_version,
            state="PAPER_AMBER",
            action="CONTINUE_PAPER_VALIDATION",
            reasons=tuple(reasons),
            window_fingerprint=fingerprint,
        )

    return PaperLearningDecision(
        strategy_id=curve.strategy_id,
        strategy_family=context.strategy_family,
        strategy_version=context.strategy_version,
        state="PAPER_GREEN",
        action="KEEP_AS_INCUMBENT_CANDIDATE",
        reasons=("POSITIVE_NET_OOS_AFTER_MODELED_COSTS", "PAPER_ONLY_NOT_LIVE_AUTHORITY"),
        window_fingerprint=fingerprint,
    )
