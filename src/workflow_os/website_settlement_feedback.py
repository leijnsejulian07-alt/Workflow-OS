from __future__ import annotations

from dataclasses import dataclass
import math

from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .scaling_control import ScalingDirective, scaling_directive
from .website_fulfillment_gate import WebsitePaymentEvidence, WebsiteScopeSnapshot
from .website_handoff_execution import WebsiteDeliveryProvenance


@dataclass(frozen=True)
class WebsiteSettlementFeedbackResult:
    reconciled_event: ReconciledEvent
    scaling: ScalingDirective


def reconcile_delivered_website_payment_and_decide_next_action(
    *,
    reconciliation_ledger: RevenueReconciliationLedger,
    snapshot: WebsiteScopeSnapshot,
    payment: WebsitePaymentEvidence,
    delivery: WebsiteDeliveryProvenance,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> WebsiteSettlementFeedbackResult:
    """Promote a delivered Website-in-a-Box payment into realized-cash truth.

    Fulfillment payment evidence alone is deliberately not scaling truth. This
    boundary additionally requires immutable confirmed-delivery provenance for
    the same opportunity and frozen scope before recording CASH_RECEIVED in the
    shared reconciliation ledger. No payment, deployment, or scheduling side
    effect is performed here.
    """
    if not isinstance(snapshot, WebsiteScopeSnapshot):
        raise TypeError("snapshot must be WebsiteScopeSnapshot")
    if not isinstance(payment, WebsitePaymentEvidence):
        raise TypeError("payment must be WebsitePaymentEvidence")
    if not isinstance(delivery, WebsiteDeliveryProvenance):
        raise TypeError("delivery must be WebsiteDeliveryProvenance")

    opportunity_id = snapshot.opportunity_id
    if payment.opportunity_id != opportunity_id:
        raise ValueError("website payment opportunity identity mismatch")
    if delivery.opportunity_id != opportunity_id:
        raise ValueError("website delivery opportunity identity mismatch")
    if delivery.scope_sha256 != snapshot.snapshot_sha256:
        raise ValueError("website delivery scope identity mismatch")
    if payment.payment_received is not True:
        raise ValueError("unconfirmed website payment cannot enter reconciliation truth")
    if not isinstance(payment.currency, str) or payment.currency.strip().upper() != "EUR":
        raise ValueError("website settlement version 1 accepts EUR only")
    if isinstance(payment.amount_eur, bool) or not isinstance(payment.amount_eur, (int, float)):
        raise ValueError("website payment amount must be a finite numeric value")
    amount_eur = float(payment.amount_eur)
    if not math.isfinite(amount_eur) or amount_eur <= 0:
        raise ValueError("website payment amount must be a finite numeric value")
    if amount_eur + 1e-9 < snapshot.fixed_price_eur:
        raise ValueError("website payment is below immutable fixed price")

    event = reconciliation_ledger.record_event(
        platform="WEBSITE_IN_A_BOX",
        external_event_id=payment.payment_reference,
        opportunity_id=opportunity_id,
        event_type="CASH_RECEIVED",
        amount_eur=amount_eur,
        occurred_at=payment.received_at,
        evidence_sha256=payment.evidence_sha256,
        currency="EUR",
    )
    if event.opportunity_id != delivery.opportunity_id:
        raise RuntimeError("reconciled website payment drifted from delivery provenance")

    directive = scaling_directive(
        reconciliation_ledger,
        opportunity_id,
        experiment_jobs=experiment_jobs,
        keep_jobs=keep_jobs,
        scale_jobs=scale_jobs,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    if directive.opportunity_id != opportunity_id:
        raise RuntimeError("website scaling directive identity mismatch")

    return WebsiteSettlementFeedbackResult(reconciled_event=event, scaling=directive)
