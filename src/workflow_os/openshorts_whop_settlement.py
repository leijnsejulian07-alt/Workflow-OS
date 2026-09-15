from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .openshorts_whop_reservation import PreparedOpenShortsWhopSubmission
from .reconciliation import RevenueReconciliationLedger
from .whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from .whop_bounty_settlement_feedback import (
    WhopBountySettlementFeedbackResult,
    reconcile_whop_bounty_payout_and_decide_next_action,
)
from .whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)


@dataclass(frozen=True)
class OpenShortsWhopSettlementResult:
    prepared: PreparedOpenShortsWhopSubmission
    provenance: WhopBountySubmissionProvenance
    settlement: WhopBountySettlementFeedbackResult


def reconcile_prepared_openshorts_whop_payout_and_decide_next_action(
    prepared: PreparedOpenShortsWhopSubmission,
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    evidence: WhopBountyPayoutEvidence,
    settlement_evidence_sha256: str,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> OpenShortsWhopSettlementResult:
    """Promote received Whop cash only through the exact OpenShorts-derived submission.

    The payout event must resolve to immutable Whop submission provenance that matches
    the side-effect reservation created from this verified OpenShorts output. This gate
    prevents a valid payout for another submission from being attached to the render
    lineage before the existing reconciled-cash scaling boundary runs.
    """
    if not isinstance(prepared, PreparedOpenShortsWhopSubmission):
        raise TypeError("prepared must be PreparedOpenShortsWhopSubmission")
    if not isinstance(provenance_ledger, WhopBountySubmissionProvenanceLedger):
        raise TypeError("provenance_ledger must be WhopBountySubmissionProvenanceLedger")
    if not isinstance(evidence, WhopBountyPayoutEvidence):
        raise TypeError("evidence must be WhopBountyPayoutEvidence")

    provenance = provenance_ledger.get_by_reference(evidence.submission_reference)
    if provenance is None:
        raise ValueError("Whop payout submission has no proven provenance")

    submission = prepared.submission
    reserved_effect = submission.reservation.side_effect
    if provenance.opportunity_id != submission.opportunity_id:
        raise RuntimeError("Whop payout opportunity is not bound to this OpenShorts submission")
    if provenance.bounty_id != submission.reservation.bounty_id:
        raise RuntimeError("Whop payout bounty is not bound to this OpenShorts submission")
    if provenance.side_effect_idempotency_key != reserved_effect.idempotency_key:
        raise RuntimeError("Whop payout side effect is not the OpenShorts-derived reservation")
    if provenance.side_effect_request_fingerprint != reserved_effect.request_fingerprint:
        raise RuntimeError("Whop payout side-effect fingerprint drifted from OpenShorts reservation")
    source_job_id = prepared.openshorts_source_job_id
    if not isinstance(source_job_id, int) or isinstance(source_job_id, bool) or source_job_id < 1:
        raise RuntimeError("OpenShorts source job identity is invalid before settlement")
    if not prepared.openshorts_idempotency_key.startswith(f"openshorts:{source_job_id}:"):
        raise RuntimeError("OpenShorts provenance is no longer bound to its durable render job")

    settlement = reconcile_whop_bounty_payout_and_decide_next_action(
        audit_ledger=audit_ledger,
        provenance_ledger=provenance_ledger,
        reconciliation_ledger=reconciliation_ledger,
        evidence=evidence,
        settlement_evidence_sha256=settlement_evidence_sha256,
        experiment_jobs=experiment_jobs,
        keep_jobs=keep_jobs,
        scale_jobs=scale_jobs,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    if settlement.payout.provenance != provenance:
        raise RuntimeError("Whop settlement provenance drifted after OpenShorts gate")

    return OpenShortsWhopSettlementResult(
        prepared=prepared,
        provenance=provenance,
        settlement=settlement,
    )
