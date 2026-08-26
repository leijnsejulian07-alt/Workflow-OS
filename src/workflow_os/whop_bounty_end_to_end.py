from __future__ import annotations

from dataclasses import dataclass

from .adapters.whop_bounty_execution import execute_reserved_whop_bounty_submission
from .adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from .adapters.whop_bounty_submission import WhopBountyDeliverable
from .credentials import CredentialProvider, CredentialRef
from .durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from .durable_whop_bounty_worker import DurableWhopBountyExecutionResult, execute_bound_whop_bounty_job
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue
from .side_effects import SideEffectLedger
from .whop_bounty_job_preparation import PreparedDurableWhopBountySubmission, prepare_durable_whop_bounty_submission
from .whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)
from .whop_bounty_submission_runtime import execute_whop_bounty_job_and_record_provenance


@dataclass(frozen=True)
class WhopBountyEndToEndResult:
    """One bounded durable Whop workforce attempt from preparation through provenance."""

    prepared: PreparedDurableWhopBountySubmission
    execution: DurableWhopBountyExecutionResult
    provenance: WhopBountySubmissionProvenance | None = None


def execute_verified_whop_bounty_job(
    verified_job: VerifiedLeasedOpportunityJob,
    deliverable: WhopBountyDeliverable,
    *,
    credential_authority_verified: bool,
    deliverable_verified: bool,
    queue: JobQueue,
    worker_id: object,
    now: object,
    binding_ledger: DurableWhopBountyBindingLedger,
    side_effect_ledger: SideEffectLedger,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    transport: WhopBountyHttpTransport,
    provenance_ledger: WhopBountySubmissionProvenanceLedger | None = None,
    max_attempts: int = 3,
) -> WhopBountyEndToEndResult:
    """Prepare, bind, execute and optionally persist payout-attribution provenance.

    Existing fail-closed boundaries remain authoritative. When a provenance ledger is
    supplied, confirmed successful execution is routed through the shared submission
    runtime so immutable payout-attribution provenance is created in the same bounded
    production path. Ambiguous/retryable execution never creates provenance.
    """

    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(deliverable, WhopBountyDeliverable):
        raise TypeError("deliverable must be WhopBountyDeliverable")
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(binding_ledger, DurableWhopBountyBindingLedger):
        raise TypeError("binding_ledger must be DurableWhopBountyBindingLedger")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")
    if provenance_ledger is not None and not isinstance(provenance_ledger, WhopBountySubmissionProvenanceLedger):
        raise TypeError("provenance_ledger must be WhopBountySubmissionProvenanceLedger")
    if not isinstance(credential_ref, CredentialRef):
        raise TypeError("credential_ref must be CredentialRef")
    if credential_ref.platform != "whop" or credential_ref.secret_name != "user_token":
        raise ValueError("Whop workforce execution requires an account-scoped Whop user_token")
    if not isinstance(transport, WhopBountyHttpTransport):
        raise TypeError("transport must be WhopBountyHttpTransport")

    prepared = prepare_durable_whop_bounty_submission(
        verified_job,
        deliverable,
        credential_authority_verified=credential_authority_verified,
        deliverable_verified=deliverable_verified,
        ledger=side_effect_ledger,
        max_attempts=max_attempts,
    )

    def _execute(reservation):
        return execute_reserved_whop_bounty_submission(
            reservation,
            ledger=side_effect_ledger,
            credential_ref=credential_ref,
            credential_provider=credential_provider,
            transport=transport,
        )

    if provenance_ledger is None:
        execution = execute_bound_whop_bounty_job(
            verified_job,
            prepared.reservation,
            queue=queue,
            worker_id=worker_id,
            now=now,
            binding_ledger=binding_ledger,
            side_effect_ledger=side_effect_ledger,
            execute_submission=_execute,
        )
        return WhopBountyEndToEndResult(prepared=prepared, execution=execution)

    runtime_result = execute_whop_bounty_job_and_record_provenance(
        verified_job,
        prepared.reservation,
        queue=queue,
        worker_id=worker_id,
        now=now,
        binding_ledger=binding_ledger,
        side_effect_ledger=side_effect_ledger,
        provenance_ledger=provenance_ledger,
        execute_submission=_execute,
    )
    return WhopBountyEndToEndResult(
        prepared=prepared,
        execution=runtime_result.execution,
        provenance=runtime_result.provenance,
    )
