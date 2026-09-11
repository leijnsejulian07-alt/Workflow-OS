from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .alpaca_paper_evidence import (
    ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
    _canonical_account_id,
    _canonical_occurred_at,
    _policy_fingerprint,
)
from .alpaca_paper_execution_costs import (
    ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION,
    AlpacaPaperExecutionEconomics,
)
from .alpaca_paper_runtime import ALPACA_PAPER_RUNTIME_POLICY_VERSION, AlpacaPaperStrategyPolicy
from .audit import AuditRevenueLedger

ALPACA_PAPER_EXECUTION_EVIDENCE_POLICY_VERSION = "alpaca-paper-execution-evidence/1"


@dataclass(frozen=True)
class AlpacaPaperExecutionEconomicsEvidenceReceipt:
    event_id: str
    event_hash: str
    strategy_id: str
    client_order_id: str
    proves_received_cash: bool = False
    proves_realized_pnl: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_EXECUTION_EVIDENCE_POLICY_VERSION


def record_alpaca_paper_execution_economics_evidence(
    *,
    audit_ledger: AuditRevenueLedger,
    account_id: str,
    strategy_policy: AlpacaPaperStrategyPolicy,
    economics: AlpacaPaperExecutionEconomics,
    occurred_at: str,
) -> AlpacaPaperExecutionEconomicsEvidenceReceipt:
    """Persist one deterministic paper execution-cost observation.

    This is paper-only model evidence. It cannot become received cash, realized
    strategy P&L, or live execution authority. Exact replay at the same observation
    time is idempotent; a later observation time produces a distinct audit event.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    account_id = _canonical_account_id(account_id)
    if not isinstance(strategy_policy, AlpacaPaperStrategyPolicy):
        raise TypeError("strategy_policy must be AlpacaPaperStrategyPolicy")
    if not isinstance(economics, AlpacaPaperExecutionEconomics):
        raise TypeError("economics must be AlpacaPaperExecutionEconomics")
    occurred_at = _canonical_occurred_at(occurred_at)
    if economics.policy_version != ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION:
        raise ValueError("execution economics policy version mismatch")
    if economics.proves_received_cash or economics.proves_realized_pnl:
        raise ValueError("paper execution economics may not prove cash or realized pnl")
    if economics.may_enter_live_execution:
        raise ValueError("paper execution economics may not grant live execution authority")
    if not economics.symbol:
        raise ValueError("paper execution economics require symbol provenance")

    strategy_fingerprint = _policy_fingerprint(strategy_policy)
    payload = {
        "provider": "alpaca",
        "mode": "PAPER_ONLY",
        "account_id": account_id,
        "strategy_id": strategy_policy.strategy_id,
        "strategy_policy_fingerprint": strategy_fingerprint,
        "runtime_policy_version": ALPACA_PAPER_RUNTIME_POLICY_VERSION,
        "evidence_policy_version": ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
        "execution_cost_policy_version": economics.policy_version,
        "execution_evidence_policy_version": ALPACA_PAPER_EXECUTION_EVIDENCE_POLICY_VERSION,
        "execution": {
            "client_order_id": economics.client_order_id,
            "symbol": economics.symbol,
            "side": economics.side,
            "filled_qty": str(economics.filled_qty),
            "reference_price": str(economics.reference_price),
            "fill_price": str(economics.fill_price),
            "reference_notional_usd": str(economics.reference_notional_usd),
            "filled_notional_usd": str(economics.filled_notional_usd),
            "observed_adverse_slippage_bps": str(economics.observed_adverse_slippage_bps),
            "modeled_slippage_bps": str(economics.modeled_slippage_bps),
            "modeled_slippage_usd": str(economics.modeled_slippage_usd),
            "modeled_fee_usd": str(economics.modeled_fee_usd),
            "modeled_total_execution_cost_usd": str(
                economics.modeled_total_execution_cost_usd
            ),
            "executed_cash_flow_usd": str(economics.executed_cash_flow_usd),
            "modeled_net_cash_flow_usd": str(economics.modeled_net_cash_flow_usd),
        },
        "proves_received_cash": False,
        "proves_realized_pnl": False,
        "may_enter_live_execution": False,
    }
    identity_material = {
        "account_id": account_id,
        "strategy_policy_fingerprint": strategy_fingerprint,
        "client_order_id": economics.client_order_id,
        "symbol": economics.symbol,
        "side": economics.side,
        "filled_qty": str(economics.filled_qty),
        "reference_price": str(economics.reference_price),
        "fill_price": str(economics.fill_price),
        "execution_cost_policy_version": economics.policy_version,
        "modeled_total_execution_cost_usd": str(
            economics.modeled_total_execution_cost_usd
        ),
        "occurred_at": occurred_at,
    }
    digest = hashlib.sha256(
        json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event_id = f"alpaca-paper-execution-economics:{digest}"
    event_hash = audit_ledger.append_event(
        event_id,
        "trading.alpaca_paper_execution_economics",
        payload,
        subject_id=strategy_policy.strategy_id,
        occurred_at=occurred_at,
    )
    return AlpacaPaperExecutionEconomicsEvidenceReceipt(
        event_id=event_id,
        event_hash=event_hash,
        strategy_id=strategy_policy.strategy_id,
        client_order_id=economics.client_order_id,
    )
