from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from .alpaca_paper_evidence import (
    ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
    _canonical_account_id,
    _canonical_occurred_at,
    _policy_fingerprint,
)
from .alpaca_paper_position_accounting import (
    ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION,
    AlpacaPaperClosedLongPosition,
)
from .alpaca_paper_runtime import ALPACA_PAPER_RUNTIME_POLICY_VERSION, AlpacaPaperStrategyPolicy
from .audit import AuditRevenueLedger

ALPACA_PAPER_POSITION_EVIDENCE_POLICY_VERSION = "alpaca-paper-position-evidence/1"


@dataclass(frozen=True)
class AlpacaPaperPositionEvidenceReceipt:
    event_id: str
    event_hash: str
    strategy_id: str
    opening_client_order_id: str
    closing_client_order_id: str
    proves_received_cash: bool = False
    proves_realized_cash_pnl: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_POSITION_EVIDENCE_POLICY_VERSION


def _validated_decimal(value: Decimal, *, field: str, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{field} must be nonnegative")
    return value


def record_alpaca_paper_position_evidence(
    *,
    audit_ledger: AuditRevenueLedger,
    account_id: str,
    strategy_policy: AlpacaPaperStrategyPolicy,
    position: AlpacaPaperClosedLongPosition,
    occurred_at: str,
) -> AlpacaPaperPositionEvidenceReceipt:
    """Persist one deterministic closed-position paper P&L observation.

    This evidence is strictly paper-only. It can feed paper learning/evaluation,
    but it never proves received cash, realized cash P&L, or live execution authority.
    Exact replay at the same observation time is idempotent.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    account_id = _canonical_account_id(account_id)
    if not isinstance(strategy_policy, AlpacaPaperStrategyPolicy):
        raise TypeError("strategy_policy must be AlpacaPaperStrategyPolicy")
    if not isinstance(position, AlpacaPaperClosedLongPosition):
        raise TypeError("position must be AlpacaPaperClosedLongPosition")
    occurred_at = _canonical_occurred_at(occurred_at)

    if position.policy_version != ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION:
        raise ValueError("position accounting policy version mismatch")
    if position.proves_received_cash or position.proves_realized_cash_pnl:
        raise ValueError("paper position may not prove cash or realized cash pnl")
    if position.may_enter_live_execution:
        raise ValueError("paper position may not grant live execution authority")
    if not position.symbol or position.symbol != position.symbol.strip():
        raise ValueError("paper position requires canonical symbol provenance")
    if not position.opening_client_order_id or not position.closing_client_order_id:
        raise ValueError("paper position requires both client order ids")
    if position.opening_client_order_id == position.closing_client_order_id:
        raise ValueError("paper position requires distinct opening and closing orders")

    _validated_decimal(position.closed_qty, field="closed_qty", positive=True)
    _validated_decimal(position.opening_reference_price, field="opening_reference_price", positive=True)
    _validated_decimal(position.closing_reference_price, field="closing_reference_price", positive=True)
    _validated_decimal(position.opening_fill_price, field="opening_fill_price", positive=True)
    _validated_decimal(position.closing_fill_price, field="closing_fill_price", positive=True)
    _validated_decimal(position.gross_reference_pnl_usd, field="gross_reference_pnl_usd")
    _validated_decimal(
        position.modeled_total_execution_cost_usd,
        field="modeled_total_execution_cost_usd",
        nonnegative=True,
    )
    _validated_decimal(position.paper_realized_pnl_usd, field="paper_realized_pnl_usd")

    expected_paper_pnl = position.gross_reference_pnl_usd - position.modeled_total_execution_cost_usd
    if position.paper_realized_pnl_usd != expected_paper_pnl:
        raise ValueError("paper position pnl is internally inconsistent")

    strategy_fingerprint = _policy_fingerprint(strategy_policy)
    payload = {
        "provider": "alpaca",
        "mode": "PAPER_ONLY",
        "account_id": account_id,
        "strategy_id": strategy_policy.strategy_id,
        "strategy_policy_fingerprint": strategy_fingerprint,
        "runtime_policy_version": ALPACA_PAPER_RUNTIME_POLICY_VERSION,
        "evidence_policy_version": ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
        "position_accounting_policy_version": position.policy_version,
        "position_evidence_policy_version": ALPACA_PAPER_POSITION_EVIDENCE_POLICY_VERSION,
        "position": {
            "symbol": position.symbol,
            "opening_client_order_id": position.opening_client_order_id,
            "closing_client_order_id": position.closing_client_order_id,
            "closed_qty": str(position.closed_qty),
            "opening_reference_price": str(position.opening_reference_price),
            "closing_reference_price": str(position.closing_reference_price),
            "opening_fill_price": str(position.opening_fill_price),
            "closing_fill_price": str(position.closing_fill_price),
            "gross_reference_pnl_usd": str(position.gross_reference_pnl_usd),
            "modeled_total_execution_cost_usd": str(position.modeled_total_execution_cost_usd),
            "paper_realized_pnl_usd": str(position.paper_realized_pnl_usd),
        },
        "proves_received_cash": False,
        "proves_realized_cash_pnl": False,
        "may_enter_live_execution": False,
    }
    identity_material = {
        "account_id": account_id,
        "strategy_policy_fingerprint": strategy_fingerprint,
        "symbol": position.symbol,
        "opening_client_order_id": position.opening_client_order_id,
        "closing_client_order_id": position.closing_client_order_id,
        "closed_qty": str(position.closed_qty),
        "paper_realized_pnl_usd": str(position.paper_realized_pnl_usd),
        "position_accounting_policy_version": position.policy_version,
        "occurred_at": occurred_at,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event_id = f"alpaca-paper-position:{digest}"
    event_hash = audit_ledger.append_event(
        event_id,
        "trading.alpaca_paper_closed_position",
        payload,
        subject_id=strategy_policy.strategy_id,
        occurred_at=occurred_at,
    )
    return AlpacaPaperPositionEvidenceReceipt(
        event_id=event_id,
        event_hash=event_hash,
        strategy_id=strategy_policy.strategy_id,
        opening_client_order_id=position.opening_client_order_id,
        closing_client_order_id=position.closing_client_order_id,
    )
