from __future__ import annotations

from dataclasses import dataclass

from .adapters.whop_bounty_execution import execute_reserved_whop_bounty_submission
from .adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from .adapters.whop_bounty_submission import WhopBountyDeliverable
from .credentials import CredentialProvider, CredentialRef
from .durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from .durable_whop_bounty_worker import (
    DurableWhopBountyExecutionResult,
    execute_bound_whop_bounty_job,
)
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue
from .side_effects import SideEffectLedger
from .whop_bounty_job_preparation import (
    PreparedDurableWhopBountySubmission,
    prepare_durable_whop_bounty_submission,
)


@dataclass(frozen=True)
class WhopBountyEndToEndResult:
    """One bounded durable Whop workforce attempt from preparation through reconciliation."""

    prepared: PreparedDurableWhopBountySubmission
    execution: DurableWhopBountyExecutionResult


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
    max_attempts: int = 3,
) -> WhopBountyEndToEndResult:
    """Prepare, bind, execute and reconcile one verified durable Whop workforce job.

    The function deliberately composes existing fail-closed boundaries rather than
    duplicating their policy. Preparation validates the immutable opportunity and
    final deliverable before reservation. The durable worker then binds that exact
    reservation to the live leased job before the official Whop executor can perform
    network I/O. Job completion is derived only from SideEffectLedger truth.
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
