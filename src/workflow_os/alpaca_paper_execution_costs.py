from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .alpaca_paper_order_outcome import AlpacaPaperOrderOutcome

ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION = "alpaca-paper-execution-cost/1"
_BPS_DENOMINATOR = Decimal("10000")


def _finite_nonnegative_decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a nonnegative decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a nonnegative decimal") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a nonnegative finite decimal")
    return number


def _finite_positive_decimal(value: object, *, field: str) -> Decimal:
    number = _finite_nonnegative_decimal(value, field=field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


@dataclass(frozen=True)
class AlpacaPaperExecutionCostPolicy:
    """Explicit conservative paper-only cost assumptions.

    These are modeling assumptions, not claims about Alpaca's actual fee schedule.
    They are intentionally versioned so evaluation evidence cannot silently change
    when the assumptions change.
    """

    modeled_fee_bps: Decimal = Decimal("5")
    minimum_adverse_slippage_bps: Decimal = Decimal("10")
    policy_version: str = ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION

    def __post_init__(self) -> None:
        fee = _finite_nonnegative_decimal(self.modeled_fee_bps, field="modeled_fee_bps")
        slippage = _finite_nonnegative_decimal(
            self.minimum_adverse_slippage_bps,
            field="minimum_adverse_slippage_bps",
        )
        if fee > Decimal("1000") or slippage > Decimal("1000"):
            raise ValueError("modeled execution costs must not exceed 1000 bps per component")
        if self.policy_version != ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION:
            raise ValueError("execution cost policy version mismatch")
        object.__setattr__(self, "modeled_fee_bps", fee)
        object.__setattr__(self, "minimum_adverse_slippage_bps", slippage)


@dataclass(frozen=True)
class AlpacaPaperExecutionEconomics:
    client_order_id: str
    side: str
    filled_qty: Decimal
    reference_price: Decimal
    fill_price: Decimal
    reference_notional_usd: Decimal
    filled_notional_usd: Decimal
    observed_adverse_slippage_bps: Decimal
    modeled_slippage_bps: Decimal
    modeled_slippage_usd: Decimal
    modeled_fee_usd: Decimal
    modeled_total_execution_cost_usd: Decimal
    executed_cash_flow_usd: Decimal
    modeled_net_cash_flow_usd: Decimal
    proves_received_cash: bool = False
    proves_realized_pnl: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION


def evaluate_paper_execution_economics(
    *,
    outcome: AlpacaPaperOrderOutcome,
    reference_price: object,
    policy: AlpacaPaperExecutionCostPolicy = AlpacaPaperExecutionCostPolicy(),
) -> AlpacaPaperExecutionEconomics:
    """Model conservative costs for one validated paper fill.

    ``reference_price`` must be an independently captured market price from the
    decision observation (for example the bar close). Modeled net cash flow is
    anchored to that reference price, so observed adverse slippage is not counted
    twice. This function intentionally does not claim realized strategy P&L: one
    execution is only a cash-flow leg until a reconciled closing leg is matched.
    """
    if not isinstance(outcome, AlpacaPaperOrderOutcome):
        raise TypeError("outcome must be AlpacaPaperOrderOutcome")
    if not isinstance(policy, AlpacaPaperExecutionCostPolicy):
        raise TypeError("policy must be AlpacaPaperExecutionCostPolicy")
    if not outcome.has_fill or outcome.filled_avg_price is None:
        raise ValueError("paper execution economics require validated fill evidence")
    if outcome.side not in {"buy", "sell"}:
        raise ValueError("unsupported paper order side")

    reference = _finite_positive_decimal(reference_price, field="reference_price")
    fill_price = _finite_positive_decimal(outcome.filled_avg_price, field="filled_avg_price")
    filled_qty = _finite_positive_decimal(outcome.filled_qty, field="filled_qty")
    reference_notional = reference * filled_qty
    filled_notional = fill_price * filled_qty

    if outcome.side == "buy":
        adverse_price_delta = max(fill_price - reference, Decimal("0"))
        executed_cash_flow = -filled_notional
        reference_cash_flow = -reference_notional
    else:
        adverse_price_delta = max(reference - fill_price, Decimal("0"))
        executed_cash_flow = filled_notional
        reference_cash_flow = reference_notional

    observed_adverse_slippage_bps = adverse_price_delta / reference * _BPS_DENOMINATOR
    modeled_slippage_bps = max(
        observed_adverse_slippage_bps,
        policy.minimum_adverse_slippage_bps,
    )
    modeled_slippage_usd = reference_notional * modeled_slippage_bps / _BPS_DENOMINATOR
    modeled_fee_usd = filled_notional * policy.modeled_fee_bps / _BPS_DENOMINATOR
    modeled_total_execution_cost = modeled_slippage_usd + modeled_fee_usd
    modeled_net_cash_flow = reference_cash_flow - modeled_total_execution_cost

    return AlpacaPaperExecutionEconomics(
        client_order_id=outcome.client_order_id,
        side=outcome.side,
        filled_qty=filled_qty,
        reference_price=reference,
        fill_price=fill_price,
        reference_notional_usd=reference_notional,
        filled_notional_usd=filled_notional,
        observed_adverse_slippage_bps=observed_adverse_slippage_bps,
        modeled_slippage_bps=modeled_slippage_bps,
        modeled_slippage_usd=modeled_slippage_usd,
        modeled_fee_usd=modeled_fee_usd,
        modeled_total_execution_cost_usd=modeled_total_execution_cost,
        executed_cash_flow_usd=executed_cash_flow,
        modeled_net_cash_flow_usd=modeled_net_cash_flow,
    )
