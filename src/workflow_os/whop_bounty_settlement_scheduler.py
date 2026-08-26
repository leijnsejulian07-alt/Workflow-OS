from __future__ import annotations

from dataclasses import dataclass

from .durable_scheduler import enqueue_controlled_candidates
from .job_queue import JobQueue, JobRecord
from .ledger import OpportunityLedger
from .opportunity_snapshot import snapshot_opportunity
from .whop_bounty_settlement_feedback import WhopBountySettlementFeedbackResult


@dataclass(frozen=True)
class WhopBountySettlementSchedulingResult:
    """Settlement feedback plus any bounded jobs scheduled for that exact opportunity."""

    feedback: WhopBountySettlementFeedbackResult
    jobs: tuple[JobRecord, ...]


def schedule_whop_bounty_settlement_feedback(
    *,
    opportunities: OpportunityLedger,
    jobs: JobQueue,
    feedback: WhopBountySettlementFeedbackResult,
    scheduled_at: str,
    job_type: str = "produce_and_publish",
    max_attempts: int = 3,
) -> WhopBountySettlementSchedulingResult:
    """Durably schedule only the opportunity whose payout was just reconciled.

    Settlement/reconciliation remains the sole source of realized-cash truth. This
    boundary does not rescan all queue candidates: it revalidates the latest stored
    Opportunity Manager decision for the exact paid opportunity, snapshots that
    opportunity, and passes the already-bounded KEEP/SCALE directive into the
    durable scheduler. PAUSE/KILL schedules nothing.
    """

    directive = feedback.scaling
    reconciled_id = feedback.payout.reconciled_event.opportunity_id
    provenance_id = feedback.payout.provenance.opportunity_id
    if directive.opportunity_id != reconciled_id or provenance_id != reconciled_id:
        raise RuntimeError("Whop settlement scheduling identity mismatch")

    if directive.action in {"PAUSE", "KILL"}:
        if directive.may_schedule or directive.max_new_jobs != 0:
            raise RuntimeError("non-schedulable Whop settlement directive is internally inconsistent")
        return WhopBountySettlementSchedulingResult(feedback=feedback, jobs=())

    if directive.action not in {"KEEP", "SCALE"}:
        raise RuntimeError("settled Whop payout may only schedule KEEP or SCALE work")
    if not directive.may_schedule:
        raise RuntimeError("schedulable Whop settlement directive unexpectedly denies scheduling")
    if not isinstance(directive.max_new_jobs, int) or isinstance(directive.max_new_jobs, bool) or not 1 <= directive.max_new_jobs <= 4:
        raise RuntimeError("Whop settlement directive has invalid max_new_jobs")
    if directive.sample_count < 1:
        raise RuntimeError("Whop settlement scheduling requires at least one reconciled sample")

    candidate = opportunities.latest_decision(reconciled_id)
    if candidate is None:
        raise RuntimeError("settled Whop opportunity has no current Opportunity Manager decision")
    if candidate.get("opportunity_id") != reconciled_id:
        raise RuntimeError("settled Whop opportunity decision identity mismatch")
    if candidate.get("decision") != "ACCEPT" or candidate.get("eligible_for_queue") is not True:
        raise RuntimeError("settled Whop opportunity is no longer eligible for scheduling")

    snapshot = snapshot_opportunity(opportunities, reconciled_id)
    controlled = dict(candidate)
    controlled["revenue_control"] = directive.to_dict()
    controlled["opportunity_snapshot"] = snapshot.payload
    controlled["opportunity_snapshot_sha256"] = snapshot.sha256

    queued = enqueue_controlled_candidates(
        jobs,
        [controlled],
        scheduled_at=scheduled_at,
        job_type=job_type,
        max_attempts=max_attempts,
    )
    if len(queued) > directive.max_new_jobs:
        raise RuntimeError("durable scheduler exceeded Whop settlement job bound")

    return WhopBountySettlementSchedulingResult(feedback=feedback, jobs=tuple(queued))
