from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .adapters.whop_bounty_execution import WhopBountyReservation
from .durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from .durable_whop_bounty_worker import (
    DurableWhopBountyExecutionResult,
    execute_bound_whop_bounty_job,
)
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue
from .side_effects import SideEffectLedger, SideEffectRecord
from .whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)


@dataclass(frozen=True)
class WhopBountySubmissionRuntimeResult:
    """Durable Whop submission plus immutable payout-attribution provenance."""

    execution: DurableWhopBountyExecutionResult
    provenance: WhopBountySubmissionProvenance | None


def execute_whop_bounty_job_and_record_provenance(
    verified_job: VerifiedLeasedOpportunityJob,
    reservation: WhopBountyReservation,
    *,
    queue: JobQueue,
    worker_id: object,
    now: object,
    binding_ledger: DurableWhopBountyBindingLedger,
    side_effect_ledger: SideEffectLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    execute_submission: Callable[[WhopBountyReservation], SideEffectRecord],
) -> WhopBountySubmissionRuntimeResult:
    """Execute one Whop bounty job and persist provenance only after proven success.

    The existing durable worker remains authoritative for queue and side-effect state.
    A submission is promoted into payout-attribution provenance only when both the
    queue job and external side effect are confirmed ``SUCCEEDED``. Retryable,
    unknown, reserved, or otherwise non-terminal-success outcomes never create
    provenance. This keeps later payout reconciliation from attributing cash to an
    ambiguous submission.
    """

    if not isinstance(provenance_ledger, WhopBountySubmissionProvenanceLedger):
        raise TypeError("provenance_ledger must be WhopBountySubmissionProvenanceLedger")

    execution = execute_bound_whop_bounty_job(
        verified_job,
        reservation,
        queue=queue,
        worker_id=worker_id,
        now=now,
        binding_ledger=binding_ledger,
        side_effect_ledger=side_effect_ledger,
        execute_submission=execute_submission,
    )

    if execution.job.state != "SUCCEEDED" or execution.side_effect.state != "SUCCEEDED":
        return WhopBountySubmissionRuntimeResult(execution=execution, provenance=None)

    provenance = provenance_ledger.record_confirmed_submission(
        execution.binding,
        side_effect_ledger=side_effect_ledger,
    )
    if provenance.opportunity_id != execution.binding.opportunity_id:
        raise RuntimeError("Whop submission provenance opportunity identity drifted")
    if provenance.bounty_id != execution.binding.bounty_id:
        raise RuntimeError("Whop submission provenance bounty identity drifted")
    if provenance.side_effect_idempotency_key != execution.side_effect.idempotency_key:
        raise RuntimeError("Whop submission provenance side-effect identity drifted")

    return WhopBountySubmissionRuntimeResult(execution=execution, provenance=provenance)
