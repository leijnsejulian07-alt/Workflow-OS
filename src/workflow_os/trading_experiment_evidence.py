from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .experiment_ledger import ExperimentLedger, ExperimentReservation
from .trading_simulation import (
    SIMULATION_POLICY_VERSION,
    TradingBacktestEvidence,
    TradingSimulationDecision,
)

TRADING_EXPERIMENT_POLICY_VERSION = "trading-experiment-evidence/1"


@dataclass(frozen=True)
class TradingExperimentResult:
    experiment_opportunity_id: str
    experiment_key: str
    status: str
    reservation: ExperimentReservation | None
    audit_event_hash: str
    proves_received_cash: bool = False
    policy_version: str = TRADING_EXPERIMENT_POLICY_VERSION


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity(evidence: TradingBacktestEvidence) -> tuple[str, str]:
    material = {
        "strategy_id": evidence.strategy_id,
        "engine": evidence.engine,
        "engine_version": evidence.engine_version,
        "evidence_sha256": evidence.evidence_sha256,
        "observed_at": evidence.observed_at,
        "policy_version": TRADING_EXPERIMENT_POLICY_VERSION,
    }
    digest = hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()
    return f"trading-simulation:{digest[:24]}", f"trading-simulation:{digest}"


def record_trading_simulation_result(
    *,
    audit_ledger: AuditRevenueLedger,
    experiment_ledger: ExperimentLedger,
    evidence: TradingBacktestEvidence,
    decision: TradingSimulationDecision,
) -> TradingExperimentResult:
    """Persist one backtest result without promoting simulated P&L to cash truth.

    Every normalized backtest result is written to the shared audit chain. Only a
    fail-closed SIMULATION_PASS receives the shared ExperimentLedger first-experiment
    reservation. Identity is deterministic from immutable backtest evidence, making
    exact replay idempotent after crashes/restarts.
    """

    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(experiment_ledger, ExperimentLedger):
        raise TypeError("experiment_ledger must be ExperimentLedger")
    if not isinstance(evidence, TradingBacktestEvidence):
        raise TypeError("evidence must be TradingBacktestEvidence")
    if not isinstance(decision, TradingSimulationDecision):
        raise TypeError("decision must be TradingSimulationDecision")
    if evidence.strategy_id != decision.strategy_id:
        raise ValueError("trading evidence and decision strategy identity mismatch")
    if evidence.proves_received_cash:
        raise ValueError("simulation evidence may never prove received cash")
    if decision.policy_version != SIMULATION_POLICY_VERSION:
        raise ValueError("trading simulation policy version mismatch")
    if decision.may_enter_live_execution:
        raise ValueError("simulation decision may not grant live execution authority")
    if decision.decision not in {"SIMULATION_PASS", "REJECT"}:
        raise ValueError("unsupported trading simulation decision")
    if decision.decision == "SIMULATION_PASS" and not decision.may_continue_simulation:
        raise ValueError("SIMULATION_PASS must allow continued simulation")
    if decision.decision == "REJECT" and decision.may_continue_simulation:
        raise ValueError("REJECT may not reserve continued simulation")

    experiment_opportunity_id, experiment_key = _identity(evidence)
    reservation: ExperimentReservation | None = None
    status = "RECORDED_REJECTED"
    if decision.decision == "SIMULATION_PASS":
        reservation = experiment_ledger.reserve_first_experiment(
            opportunity_id=experiment_opportunity_id,
            experiment_key=experiment_key,
            reserved_at=evidence.observed_at,
        )
        status = "RESERVED_SIMULATION_EXPERIMENT"

    audit_payload = {
        "experiment_opportunity_id": experiment_opportunity_id,
        "experiment_key": experiment_key,
        "status": status,
        "simulation_policy_version": decision.policy_version,
        "experiment_policy_version": TRADING_EXPERIMENT_POLICY_VERSION,
        "backtest": evidence.to_dict(),
        "decision": decision.to_dict(),
        "proves_received_cash": False,
    }
    event_id = "trading-simulation-result:" + hashlib.sha256(
        experiment_key.encode("utf-8")
    ).hexdigest()
    audit_event_hash = audit_ledger.append_event(
        event_id,
        "trading.simulation_result",
        audit_payload,
        subject_id=experiment_opportunity_id,
        occurred_at=evidence.observed_at,
    )

    return TradingExperimentResult(
        experiment_opportunity_id=experiment_opportunity_id,
        experiment_key=experiment_key,
        status=status,
        reservation=reservation,
        audit_event_hash=audit_event_hash,
    )
