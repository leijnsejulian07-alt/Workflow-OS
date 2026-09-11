from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .alpaca_paper_runtime import (
    ALPACA_PAPER_RUNTIME_POLICY_VERSION,
    AlpacaPaperRuntimeResult,
    AlpacaPaperStrategyPolicy,
)
from .audit import AuditRevenueLedger

ALPACA_PAPER_EVIDENCE_POLICY_VERSION = "alpaca-paper-evidence/1"


@dataclass(frozen=True)
class AlpacaPaperEvidenceReceipt:
    event_id: str
    event_hash: str
    strategy_id: str
    runtime_status: str
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
    if not isinstance(policy, AlpacaPaperStrategyPolicy):
        raise TypeError("policy must be AlpacaPaperStrategyPolicy")
    payload = asdict(policy)
    payload["runtime_policy_version"] = ALPACA_PAPER_RUNTIME_POLICY_VERSION
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
    if not isinstance(occurred_at, str) or not occurred_at.strip() or occurred_at != occurred_at.strip():
        raise ValueError("occurred_at must be a canonical timezone-aware timestamp")

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
