from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from .alpaca_paper_runtime import (
    ALPACA_PAPER_RUNTIME_POLICY_VERSION,
    AlpacaPaperRuntimeResult,
    AlpacaPaperStrategyPolicy,
    _strategy_policy_fingerprint,
)
from .audit import AuditRevenueLedger

ALPACA_PAPER_EVIDENCE_POLICY_VERSION = "alpaca-paper-evidence/2"


@dataclass(frozen=True)
class AlpacaPaperEvidenceReceipt:
    event_id: str
    event_hash: str
    strategy_id: str
    runtime_status: str
    proves_received_cash: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_EVIDENCE_POLICY_VERSION


@dataclass(frozen=True)
class AlpacaPaperOutcomeEvidenceReceipt:
    event_id: str
    event_hash: str
    strategy_id: str
    client_order_id: str
    order_status: str
    terminal: bool
    has_fill: bool
    proves_received_cash: bool = False
    may_enter_live_execution: bool = False
    policy_version: str = ALPACA_PAPER_EVIDENCE_POLICY_VERSION


def _canonical_account_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 200
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ValueError("paper account_id is required, canonical and bounded")
    return value


def _policy_fingerprint(policy: AlpacaPaperStrategyPolicy) -> str:
    """Use the exact runtime/side-effect policy identity for audit provenance."""
    return _strategy_policy_fingerprint(policy)


def _canonical_occurred_at(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("occurred_at must be a canonical timezone-aware timestamp")
    return value


def record_alpaca_paper_runtime_evidence(
    *,
    audit_ledger: AuditRevenueLedger,
    account_id: str,
    policy: AlpacaPaperStrategyPolicy,
    result: AlpacaPaperRuntimeResult,
    occurred_at: str,
) -> AlpacaPaperEvidenceReceipt:
    """Append one idempotent paper-runtime result to the shared audit chain.

    The record contains no credentials and can never prove received cash or grant
    live execution authority. ``occurred_at`` is explicit so failures without a
    market observation are still deterministic under replay.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    account_id = _canonical_account_id(account_id)
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise TypeError("policy must be AlpacaPaperStrategyPolicy")
    if not isinstance(result, AlpacaPaperRuntimeResult):
        raise TypeError("result must be AlpacaPaperRuntimeResult")
    occurred_at = _canonical_occurred_at(occurred_at)

    observation = result.observation
    decision = result.decision
    side_effect = result.side_effect
    payload = {
        "provider": "alpaca",
        "mode": "PAPER_ONLY",
        "account_id": account_id,
        "strategy_id": policy.strategy_id,
        "strategy_policy_fingerprint": _policy_fingerprint(policy),
        "runtime_policy_version": ALPACA_PAPER_RUNTIME_POLICY_VERSION,
        "evidence_policy_version": ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
        "runtime_status": result.status,
        "observation": None
        if observation is None
        else {
            "symbol": observation.symbol,
            "timestamp": observation.timestamp,
            "open": observation.open,
            "high": observation.high,
            "low": observation.low,
            "close": observation.close,
            "volume": observation.volume,
            "trade_count": observation.trade_count,
            "vwap": observation.vwap,
            "feed": observation.feed,
            "request_id": observation.request_id,
        },
        "decision": None
        if decision is None
        else {
            "action": decision.action,
            "reason": decision.reason,
            "client_order_id": decision.client_order_id,
        },
        "side_effect": None
        if side_effect is None
        else {
            "idempotency_key": side_effect.idempotency_key,
            "state": side_effect.state,
            "attempt_count": side_effect.attempt_count,
            "max_attempts": side_effect.max_attempts,
            "external_reference": side_effect.external_reference,
        },
        "proves_received_cash": False,
        "may_enter_live_execution": False,
    }
    identity_material = {
        "account_id": account_id,
        "strategy_policy_fingerprint": payload["strategy_policy_fingerprint"],
        "runtime_status": result.status,
        "occurred_at": occurred_at,
        "observation_timestamp": None if observation is None else observation.timestamp,
        "client_order_id": None if decision is None else decision.client_order_id,
        "side_effect_state": None if side_effect is None else side_effect.state,
        "side_effect_attempt_count": None if side_effect is None else side_effect.attempt_count,
    }
    identity = hashlib.sha256(
        json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event_id = f"alpaca-paper-runtime:{identity}"
    event_hash = audit_ledger.append_event(
        event_id,
        "trading.alpaca_paper_runtime",
        payload,
        subject_id=policy.strategy_id,
        occurred_at=occurred_at,
    )
    return AlpacaPaperEvidenceReceipt(
        event_id=event_id,
        event_hash=event_hash,
        strategy_id=policy.strategy_id,
        runtime_status=result.status,
    )


def record_alpaca_paper_order_outcome_evidence(
    *,
    audit_ledger: AuditRevenueLedger,
    account_id: str,
    policy: AlpacaPaperStrategyPolicy,
    outcome: AlpacaPaperOrderOutcome,
    occurred_at: str,
) -> AlpacaPaperOutcomeEvidenceReceipt:
    """Append one immutable paper order/fill snapshot to the shared audit chain.

    This records execution evidence only. Paper fills are simulations, are never
    inserted into the cash ledger, and cannot grant live execution authority.
    Distinct order-state/fill snapshots get distinct event identities while exact
    replay remains idempotent.
    """
    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    account_id = _canonical_account_id(account_id)
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise TypeError("policy must be AlpacaPaperStrategyPolicy")
    if not isinstance(outcome, AlpacaPaperOrderOutcome):
        raise TypeError("outcome must be AlpacaPaperOrderOutcome")
    occurred_at = _canonical_occurred_at(occurred_at)

    policy_fingerprint = _policy_fingerprint(policy)
    filled_avg_price = None if outcome.filled_avg_price is None else str(outcome.filled_avg_price)
    filled_notional_usd = outcome.filled_notional_usd
    payload = {
        "provider": "alpaca",
        "mode": "PAPER_ONLY",
        "account_id": account_id,
        "strategy_id": policy.strategy_id,
        "strategy_policy_fingerprint": policy_fingerprint,
        "runtime_policy_version": ALPACA_PAPER_RUNTIME_POLICY_VERSION,
        "evidence_policy_version": ALPACA_PAPER_EVIDENCE_POLICY_VERSION,
        "order": {
            "external_order_id": outcome.external_order_id,
            "client_order_id": outcome.client_order_id,
            "symbol": outcome.symbol,
            "side": outcome.side,
            "status": outcome.status,
            "ordered_qty": str(outcome.ordered_qty),
            "filled_qty": str(outcome.filled_qty),
            "filled_avg_price": filled_avg_price,
            "filled_notional_usd": None if filled_notional_usd is None else str(filled_notional_usd),
            "submitted_at": outcome.submitted_at.isoformat(),
            "filled_at": None if outcome.filled_at is None else outcome.filled_at.isoformat(),
            "terminal": outcome.terminal,
            "has_fill": outcome.has_fill,
        },
        "proves_received_cash": False,
        "may_enter_live_execution": False,
    }
    identity_material = {
        "account_id": account_id,
        "strategy_policy_fingerprint": policy_fingerprint,
        "external_order_id": outcome.external_order_id,
        "client_order_id": outcome.client_order_id,
        "status": outcome.status,
        "filled_qty": str(outcome.filled_qty),
        "filled_avg_price": filled_avg_price,
        "filled_at": None if outcome.filled_at is None else outcome.filled_at.isoformat(),
        "terminal": outcome.terminal,
        "occurred_at": occurred_at,
    }
    identity = hashlib.sha256(
        json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event_id = f"alpaca-paper-outcome:{identity}"
    event_hash = audit_ledger.append_event(
        event_id,
        "trading.alpaca_paper_order_outcome",
        payload,
        subject_id=policy.strategy_id,
        occurred_at=occurred_at,
    )
    return AlpacaPaperOutcomeEvidenceReceipt(
        event_id=event_id,
        event_hash=event_hash,
        strategy_id=policy.strategy_id,
        client_order_id=outcome.client_order_id,
        order_status=outcome.status,
        terminal=outcome.terminal,
        has_fill=outcome.has_fill,
    )
