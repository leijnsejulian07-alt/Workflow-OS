from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .alpaca_paper_execution_costs import (
    ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION,
    AlpacaPaperExecutionEconomics,
)

ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION = "alpaca-paper-position-accounting/1"


@dataclass(frozen=True)
class AlpacaPaperClosedLongPosition:
    symbol: str
    opening_client_order_id: str
    closing_client_order_id: str
    closed_qty: Decimal
    opening_reference_price: Decimal
    closing_reference_price: Decimal
    opening_fill_price: Decimal
    closing_fill_price: Decimal
    gross_reference_pnl_usd: Decimal
    modeled_total_execution_cost_usd: Decimal
    paper_realized_pnl_usd: Decimal
    proves_received_cash: bool = False
    proves_realized_cash_pnl: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION


def match_closed_long_paper_position(
    *,
    opening: AlpacaPaperExecutionEconomics,
    closing: AlpacaPaperExecutionEconomics,
) -> AlpacaPaperClosedLongPosition:
    """Fail closed unless two paper executions fully close one long position.

    The first supported accounting slice is deliberately narrow: one complete buy
    fill matched to one complete sell fill of exactly the same symbol and quantity.
    Partial inventory, scale-in/scale-out, shorts, and cross-policy matching are
    rejected until a position inventory ledger can model them explicitly.
    """
    if not isinstance(opening, AlpacaPaperExecutionEconomics):
        raise TypeError("opening must be AlpacaPaperExecutionEconomics")
    if not isinstance(closing, AlpacaPaperExecutionEconomics):
        raise TypeError("closing must be AlpacaPaperExecutionEconomics")
    if opening.policy_version != ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION:
        raise ValueError("opening execution cost policy version mismatch")
    if closing.policy_version != ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION:
        raise ValueError("closing execution cost policy version mismatch")
    if opening.side != "buy" or closing.side != "sell":
        raise ValueError("closed long paper position requires buy then sell")
    if not opening.symbol or not closing.symbol or opening.symbol != closing.symbol:
        raise ValueError("closed paper position requires identical symbol provenance")
    if not opening.client_order_id or not closing.client_order_id:
        raise ValueError("paper executions require client order ids")
    if opening.client_order_id == closing.client_order_id:
        raise ValueError("opening and closing executions must be distinct orders")
    if opening.filled_qty <= 0 or closing.filled_qty <= 0:
        raise ValueError("paper executions require positive filled quantity")
    if opening.filled_qty != closing.filled_qty:
        raise ValueError("partial inventory matching is not supported")
    if opening.proves_received_cash or closing.proves_received_cash:
        raise ValueError("paper executions may not prove received cash")
    if opening.proves_realized_pnl or closing.proves_realized_pnl:
        raise ValueError("individual execution legs may not prove realized pnl")
    if opening.may_enter_live_execution or closing.may_enter_live_execution:
        raise ValueError("paper executions may not grant live execution authority")

    gross_reference_pnl = closing.reference_notional_usd - opening.reference_notional_usd
    modeled_total_execution_cost = (
        opening.modeled_total_execution_cost_usd
        + closing.modeled_total_execution_cost_usd
    )
    paper_realized_pnl = opening.modeled_net_cash_flow_usd + closing.modeled_net_cash_flow_usd

    expected_paper_realized_pnl = gross_reference_pnl - modeled_total_execution_cost
    if paper_realized_pnl != expected_paper_realized_pnl:
        raise ValueError("execution economics are internally inconsistent")

    return AlpacaPaperClosedLongPosition(
        symbol=opening.symbol,
        opening_client_order_id=opening.client_order_id,
        closing_client_order_id=closing.client_order_id,
        closed_qty=opening.filled_qty,
        opening_reference_price=opening.reference_price,
        closing_reference_price=closing.reference_price,
        opening_fill_price=opening.fill_price,
        closing_fill_price=closing.fill_price,
        gross_reference_pnl_usd=gross_reference_pnl,
        modeled_total_execution_cost_usd=modeled_total_execution_cost,
        paper_realized_pnl_usd=paper_realized_pnl,
    )
