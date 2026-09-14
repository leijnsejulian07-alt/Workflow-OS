from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .job_queue import JobQueue
from .ledger import OpportunityLedger
from .openshorts_whop_reservation import PreparedOpenShortsWhopSubmission
from .openshorts_whop_settlement import (
    OpenShortsWhopSettlementResult,
    reconcile_prepared_openshorts_whop_payout_and_decide_next_action,
)
from .reconciliation import RevenueReconciliationLedger
from .whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from .whop_bounty_settlement_scheduler import (
    WhopBountySettlementSchedulingResult,
    schedule_whop_bounty_settlement_feedback,
)
from .whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger


@dataclass(frozen=True)
class OpenShortsWhopSettlementSchedulingResult:
    """Verified OpenShorts settlement plus bounded durable follow-up work."""

    settlement: OpenShortsWhopSettlementResult
    scheduling: WhopBountySettlementSchedulingResult


def reconcile_and_schedule_prepared_openshorts_whop_payout(
    prepared: PreparedOpenShortsWhopSubmission,
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    opportunities: OpportunityLedger,
    jobs: JobQueue,
    evidence: WhopBountyPayoutEvidence,
    settlement_evidence_sha256: str,
    scheduled_at: str,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
    job_type: str = "produce_and_publish",
    max_attempts: int = 3,
) -> OpenShortsWhopSettlementSchedulingResult:
    """Reconcile verified received cash, then durably schedule only its bounded directive.

    The OpenShorts-derived Whop reservation is revalidated by the settlement gate first.
    Only the resulting reconciled-cash feedback may reach the existing settlement
    scheduler. The scheduler independently revalidates current Opportunity Manager
    eligibility and preserves PAUSE/KILL as zero-work outcomes.
    """

    settlement = reconcile_prepared_openshorts_whop_payout_and_decide_next_action(
        prepared,
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

    opportunity_id = prepared.submission.opportunity_id
    feedback = settlement.settlement
    if feedback.payout.provenance.opportunity_id != opportunity_id:
        raise RuntimeError("OpenShorts settlement provenance identity mismatch before scheduling")
    if feedback.payout.reconciled_event.opportunity_id != opportunity_id:
        raise RuntimeError("OpenShorts reconciled cash identity mismatch before scheduling")
    if feedback.scaling.opportunity_id != opportunity_id:
        raise RuntimeError("OpenShorts scaling directive identity mismatch before scheduling")

    scheduling = schedule_whop_bounty_settlement_feedback(
        opportunities=opportunities,
        jobs=jobs,
        feedback=feedback,
        scheduled_at=scheduled_at,
        job_type=job_type,
        max_attempts=max_attempts,
    )
    if scheduling.feedback != feedback:
        raise RuntimeError("OpenShorts settlement feedback drifted during durable scheduling")

    return OpenShortsWhopSettlementSchedulingResult(
        settlement=settlement,
        scheduling=scheduling,
    )
