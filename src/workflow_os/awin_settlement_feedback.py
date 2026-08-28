from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import math
import re
from typing import Any, Mapping

from .awin_transaction_evidence import AwinTransactionEvidence
from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .scaling_control import ScalingDirective, scaling_directive

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


@dataclass(frozen=True)
class AwinPayoutAllocationEvidence:
    payment_id: str
    transaction_id: str
    opportunity_id: str
    publisher_id: int
    amount_cents: int
    currency: str
    paid_at: str
    bank_received_at: str
    bank_reference: str
    payment_evidence_sha256: str
    bank_evidence_sha256: str


@dataclass(frozen=True)
class AwinSettlementFeedbackResult:
    payout: AwinPayoutAllocationEvidence
    reconciled_event: ReconciledEvent
    scaling: ScalingDirective


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"invalid {name}")
    return cleaned


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _timestamp(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp")
    return parsed.isoformat()


def _amount_to_cents(value: object) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("amount_eur must be a positive finite amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount_eur must be a positive finite amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount_eur must be a positive finite amount")
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized != amount:
        raise ValueError("amount_eur may have at most two decimal places")
    cents = int(quantized * 100)
    if cents <= 0 or cents > 100_000_000_000:
        raise ValueError("amount_eur is outside supported bounds")
    return cents


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    cleaned = value.strip()
    if not _SHA256_RE.fullmatch(cleaned):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return cleaned


def normalize_awin_payout_allocation(
    raw: Mapping[str, Any], *, transaction: AwinTransactionEvidence
) -> AwinPayoutAllocationEvidence:
    """Normalize payout allocation plus independent bank-receipt evidence.

    Awin transaction approval is deliberately insufficient. This boundary only
    promotes cash when payment-history/self-billing allocation evidence and an
    independently observed bank receipt agree on the exact approved transaction.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("raw Awin payout allocation must be a mapping")
    if not isinstance(transaction, AwinTransactionEvidence):
        raise TypeError("transaction must be AwinTransactionEvidence")
    if transaction.status != "approved":
        raise ValueError("only approved Awin transactions may be reconciled to payout")
    if transaction.commission_cents <= 0:
        raise ValueError("zero-value Awin commission cannot become received cash")

    payment_id = _identifier(raw.get("payment_id"), "payment_id")
    transaction_id = _identifier(raw.get("transaction_id"), "transaction_id")
    opportunity_id = _identifier(raw.get("opportunity_id"), "opportunity_id")
    publisher_id = _positive_int(raw.get("publisher_id"), "publisher_id")
    if transaction_id != transaction.transaction_id:
        raise ValueError("Awin payout transaction identity mismatch")
    if opportunity_id != transaction.opportunity_id:
        raise ValueError("Awin payout opportunity identity mismatch")
    if publisher_id != transaction.publisher_id:
        raise ValueError("Awin payout publisher identity mismatch")
    if raw.get("currency") != "EUR" or transaction.currency != "EUR":
        raise ValueError("Awin settlement version 1 accepts EUR only")

    amount_cents = _amount_to_cents(raw.get("amount_eur"))
    if amount_cents != transaction.commission_cents:
        raise ValueError("Awin payout allocation amount does not match approved commission")

    paid_at = _timestamp(raw.get("paid_at"), "paid_at")
    bank_received_at = _timestamp(raw.get("bank_received_at"), "bank_received_at")
    if datetime.fromisoformat(bank_received_at) < datetime.fromisoformat(paid_at):
        raise ValueError("bank receipt cannot predate Awin payout")

    return AwinPayoutAllocationEvidence(
        payment_id=payment_id,
        transaction_id=transaction_id,
        opportunity_id=opportunity_id,
        publisher_id=publisher_id,
        amount_cents=amount_cents,
        currency="EUR",
        paid_at=paid_at,
        bank_received_at=bank_received_at,
        bank_reference=_identifier(raw.get("bank_reference"), "bank_reference"),
        payment_evidence_sha256=_digest(
            raw.get("payment_evidence_sha256"), "payment_evidence_sha256"
        ),
        bank_evidence_sha256=_digest(
            raw.get("bank_evidence_sha256"), "bank_evidence_sha256"
        ),
    )


def reconcile_awin_payout_and_decide_next_action(
    raw: Mapping[str, Any],
    *,
    transaction: AwinTransactionEvidence,
    reconciliation_ledger: RevenueReconciliationLedger,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> AwinSettlementFeedbackResult:
    payout = normalize_awin_payout_allocation(raw, transaction=transaction)

    evidence_material = (
        payout.payment_evidence_sha256
        + ":"
        + payout.bank_evidence_sha256
        + ":"
        + payout.bank_reference
    )
    combined_evidence_sha256 = hashlib.sha256(evidence_material.encode("utf-8")).hexdigest()
    external_event_id = f"{payout.payment_id}:{payout.transaction_id}"
    event = reconciliation_ledger.record_event(
        platform="AWIN",
        external_event_id=external_event_id,
        opportunity_id=payout.opportunity_id,
        event_type="CASH_RECEIVED",
        amount_eur=payout.amount_cents / 100,
        occurred_at=payout.bank_received_at,
        evidence_sha256=combined_evidence_sha256,
        currency="EUR",
    )
    if event.opportunity_id != transaction.opportunity_id:
        raise RuntimeError("reconciled Awin payout drifted from transaction attribution")

    directive = scaling_directive(
        reconciliation_ledger,
        payout.opportunity_id,
        experiment_jobs=experiment_jobs,
        keep_jobs=keep_jobs,
        scale_jobs=scale_jobs,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    if directive.opportunity_id != payout.opportunity_id:
        raise RuntimeError("Awin scaling directive identity mismatch")

    return AwinSettlementFeedbackResult(
        payout=payout, reconciled_event=event, scaling=directive
    )
