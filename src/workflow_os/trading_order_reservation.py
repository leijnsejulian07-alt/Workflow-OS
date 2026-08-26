from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .side_effects import SideEffectLedger, SideEffectRecord
from .trading_order_risk_gate import (
    TradingOrderIntent,
    TradingOrderRiskDecision,
    TradingRiskSnapshot,
    evaluate_trading_order_risk,
)

TRADING_ORDER_ACTION = "TRADING_ORDER"


@dataclass(frozen=True)
class TradingOrderReservationResult:
    decision: TradingOrderRiskDecision
    reservation: SideEffectRecord | None

    @property
    def reserved(self) -> bool:
        return self.reservation is not None


def _payload(*, snapshot: TradingRiskSnapshot, intent: TradingOrderIntent) -> dict[str, Any]:
    """Canonical, bounded order intent evidence stored before any broker side effect.

    Secrets, credentials and broker tokens are deliberately absent. The payload binds
    the account/provider/program identity and risk-relevant order fields so an
    idempotency key cannot later be replayed for a different order.
    """

    return {
        "provider": snapshot.provider,
        "program": snapshot.program,
        "account_id": snapshot.account_id,
        "symbol": intent.symbol,
        "side": intent.side,
        "quantity_contracts": intent.quantity_contracts,
        "max_loss_if_filled": intent.max_loss_if_filled,
        "risk_policy_version": evaluate_trading_order_risk(
            snapshot=snapshot, intent=intent
        ).policy_version,
    }


def evaluate_and_reserve_trading_order(
    *,
    ledger: SideEffectLedger,
    snapshot: TradingRiskSnapshot,
    intent: TradingOrderIntent,
    max_attempts: int = 2,
) -> TradingOrderReservationResult:
    """Evaluate risk and, only on PASS, reserve an idempotent future order side effect.

    This boundary never begins execution and never calls a broker. A successful result
    leaves the shared SideEffectLedger record in RESERVED. The future broker adapter
    must explicitly call ``begin_attempt`` and retain the existing UNKNOWN/reconciliation
    semantics for ambiguous external outcomes.
    """

    decision = evaluate_trading_order_risk(snapshot=snapshot, intent=intent)
    if not decision.may_reserve_side_effect:
        return TradingOrderReservationResult(decision=decision, reservation=None)

    target = f"{snapshot.provider.strip().upper()}:{snapshot.account_id.strip()}"
    reservation = ledger.reserve(
        idempotency_key=intent.idempotency_key,
        action=TRADING_ORDER_ACTION,
        target=target,
        payload=_payload(snapshot=snapshot, intent=intent),
        max_attempts=max_attempts,
    )
    if reservation.state != "RESERVED":
        # Exact idempotent replay may legitimately return the same RESERVED row.
        # Any progressed/ambiguous state belongs to the execution/reconciliation layer,
        # not to a fresh pre-order reservation request.
        raise RuntimeError(
            f"trading order reservation is not fresh/reservable from state {reservation.state}"
        )
    return TradingOrderReservationResult(decision=decision, reservation=reservation)
