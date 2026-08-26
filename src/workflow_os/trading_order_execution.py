from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .side_effects import SideEffectLedger, SideEffectRecord
from .trading_order_reservation import TradingOrderReservationResult


@dataclass(frozen=True)
class TradingOrderAttemptResult:
    """Bounded result contract returned by a future official broker adapter.

    APPLIED means the venue confirmed an order side effect and supplied a stable
    external order/reference identifier. NOT_APPLIED is only valid when the
    adapter has evidence that no order was accepted. UNKNOWN is mandatory for
    timeouts, disconnects after dispatch, malformed responses, or any ambiguous
    state where blindly retrying could duplicate an order.
    """

    outcome: Literal["APPLIED", "NOT_APPLIED", "UNKNOWN"]
    external_reference: str | None = None


@dataclass(frozen=True)
class TradingOrderReconciliationResult:
    """Evidence returned by an account/broker reconciliation probe."""

    outcome: Literal["FOUND_APPLIED", "PROVEN_NOT_APPLIED", "STILL_UNKNOWN"]
    external_reference: str | None = None


def execute_reserved_trading_order(
    reservation: TradingOrderReservationResult,
    *,
    ledger: SideEffectLedger,
    submit: Callable[[], TradingOrderAttemptResult],
) -> SideEffectRecord:
    """Execute one already-reserved trading order attempt fail-closed.

    This function deliberately has no broker SDK or credentials. A future
    official adapter is injected via ``submit``. The shared SideEffectLedger is
    moved to EXECUTING before the adapter is called. Any exception or ambiguous
    adapter result becomes UNKNOWN and therefore cannot be retried blindly.
    """

    if not reservation.decision.may_reserve_side_effect or reservation.reservation is None:
        raise RuntimeError("trading order must pass risk checks and be reserved before execution")

    key = reservation.reservation.idempotency_key
    current = ledger.get(key)
    if current is None:
        raise RuntimeError("reserved trading side effect is missing")
    if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
        raise RuntimeError(f"trading order is not execution-authorized from state {current.state}")

    ledger.begin_attempt(key)
    try:
        result = submit()
    except Exception:
        ledger.mark_failed(key, definitely_not_applied=False)
        raise

    if not isinstance(result, TradingOrderAttemptResult):
        ledger.mark_failed(key, definitely_not_applied=False)
        raise TypeError("broker adapter returned an invalid trading order result")

    if result.outcome == "APPLIED":
        reference = result.external_reference.strip() if isinstance(result.external_reference, str) else ""
        if not reference:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("APPLIED trading result requires a stable external reference")
        try:
            return ledger.mark_succeeded(key, external_reference=reference)
        except Exception:
            latest = ledger.get(key)
            if latest is not None and latest.state == "EXECUTING":
                ledger.mark_failed(key, definitely_not_applied=False)
            raise

    if result.outcome == "NOT_APPLIED":
        if result.external_reference is not None:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("NOT_APPLIED trading result cannot include an external reference")
        return ledger.mark_failed(key, definitely_not_applied=True)

    if result.outcome == "UNKNOWN":
        if result.external_reference is not None:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("UNKNOWN trading result cannot include an external reference")
        return ledger.mark_failed(key, definitely_not_applied=False)

    ledger.mark_failed(key, definitely_not_applied=False)
    raise ValueError("unsupported trading order outcome")


def reconcile_unknown_trading_order(
    *,
    ledger: SideEffectLedger,
    idempotency_key: str,
    reconcile: Callable[[], TradingOrderReconciliationResult],
) -> SideEffectRecord:
    """Resolve an UNKNOWN trading side effect using explicit broker/account evidence.

    Reconciliation never dispatches a new order. FOUND_APPLIED binds the stable
    external reference and marks success; PROVEN_NOT_APPLIED re-authorizes a
    bounded retry; STILL_UNKNOWN preserves the UNKNOWN state so no blind retry
    can occur.
    """

    current = ledger.get(idempotency_key)
    if current is None:
        raise KeyError(idempotency_key)
    if current.state != "UNKNOWN":
        raise RuntimeError("only UNKNOWN trading side effects may be reconciled")

    result = reconcile()
    if not isinstance(result, TradingOrderReconciliationResult):
        raise TypeError("broker reconciliation returned an invalid result")

    if result.outcome == "FOUND_APPLIED":
        reference = result.external_reference.strip() if isinstance(result.external_reference, str) else ""
        if not reference:
            raise ValueError("FOUND_APPLIED reconciliation requires a stable external reference")
        return ledger.mark_succeeded(idempotency_key, external_reference=reference)

    if result.outcome == "PROVEN_NOT_APPLIED":
        if result.external_reference is not None:
            raise ValueError("PROVEN_NOT_APPLIED cannot include an external reference")
        return ledger.reconcile_not_applied(idempotency_key)

    if result.outcome == "STILL_UNKNOWN":
        if result.external_reference is not None:
            raise ValueError("STILL_UNKNOWN cannot include an external reference")
        latest = ledger.get(idempotency_key)
        if latest is None:
            raise RuntimeError("trading side effect disappeared during reconciliation")
        return latest

    raise ValueError("unsupported trading reconciliation outcome")
