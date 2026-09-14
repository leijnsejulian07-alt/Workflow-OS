from __future__ import annotations

from dataclasses import dataclass

from .adapters.whop_bounty_execution import execute_reserved_whop_bounty_submission
from .adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from .credentials import CredentialProvider, CredentialRef
from .durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from .durable_whop_bounty_worker import DurableWhopBountyExecutionResult
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue
from .openshorts_whop_reservation import PreparedOpenShortsWhopSubmission
from .side_effects import SideEffectLedger
from .whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)
from .whop_bounty_submission_runtime import execute_whop_bounty_job_and_record_provenance


@dataclass(frozen=True)
class OpenShortsWhopExecutionResult:
    prepared: PreparedOpenShortsWhopSubmission
    execution: DurableWhopBountyExecutionResult
    provenance: WhopBountySubmissionProvenance | None


def _verify_prepared_openshorts_binding(
    verified_job: VerifiedLeasedOpportunityJob,
    prepared: PreparedOpenShortsWhopSubmission,
) -> None:
    record = verified_job.job
    if record.job_type == "produce_and_publish":
        if not prepared.openshorts_idempotency_key.startswith(f"openshorts:{record.job_id}:"):
            raise RuntimeError("prepared OpenShorts provenance is not bound to this durable job")
        return
    if record.job_type != "submit_reward":
        raise RuntimeError("prepared OpenShorts Whop execution requires an approved durable job type")

    upstream = verified_job.payload.get("upstream_render")
    if not isinstance(upstream, dict):
        raise RuntimeError("submit_reward job is missing upstream render provenance")
    source_job_id = upstream.get("source_job_id")
    if not isinstance(source_job_id, int) or isinstance(source_job_id, bool) or source_job_id < 1:
        raise RuntimeError("upstream render source job identity is invalid")
    if not prepared.openshorts_idempotency_key.startswith(f"openshorts:{source_job_id}:"):
        raise RuntimeError("prepared OpenShorts provenance is not bound to the upstream render job")
    if upstream.get("openshorts_idempotency_key") != prepared.openshorts_idempotency_key:
        raise RuntimeError("prepared OpenShorts idempotency provenance drifted before execution")
    if upstream.get("provider_job_id") != prepared.openshorts_provider_job_id:
        raise RuntimeError("prepared OpenShorts provider job provenance drifted before execution")
    if upstream.get("clip_index") != prepared.openshorts_clip_index:
        raise RuntimeError("prepared OpenShorts clip provenance drifted before execution")
    if upstream.get("evidence_sha256") != prepared.openshorts_evidence_sha256:
        raise RuntimeError("prepared OpenShorts evidence provenance drifted before execution")


def execute_prepared_openshorts_whop_submission(
    verified_job: VerifiedLeasedOpportunityJob,
    prepared: PreparedOpenShortsWhopSubmission,
    *,
    queue: JobQueue,
    worker_id: object,
    now: object,
    binding_ledger: DurableWhopBountyBindingLedger,
    side_effect_ledger: SideEffectLedger,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    transport: WhopBountyHttpTransport,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
) -> OpenShortsWhopExecutionResult:
    """Execute one already-reserved OpenShorts-derived Whop submission.

    The reservation from the verified OpenShorts handoff is the only deliverable
    authority accepted here. This function never rebuilds or mutates the deliverable
    before external I/O, so provider-output provenance remains bound to the exact
    Whop side effect that later payout attribution references.
    """
    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(prepared, PreparedOpenShortsWhopSubmission):
        raise TypeError("prepared must be PreparedOpenShortsWhopSubmission")
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
    if not isinstance(provenance_ledger, WhopBountySubmissionProvenanceLedger):
        raise TypeError("provenance_ledger must be WhopBountySubmissionProvenanceLedger")

    record = verified_job.job
    submission = prepared.submission
    if submission.job_id != record.job_id:
        raise RuntimeError("prepared OpenShorts Whop submission job identity drifted")
    if submission.opportunity_id != record.opportunity_id:
        raise RuntimeError("prepared OpenShorts Whop submission opportunity identity drifted")
    _verify_prepared_openshorts_binding(verified_job, prepared)

    current = side_effect_ledger.get(submission.reservation.side_effect.idempotency_key)
    if current is None:
        raise RuntimeError("prepared Whop side effect disappeared before execution")
    if current.request_fingerprint != submission.reservation.side_effect.request_fingerprint:
        raise RuntimeError("prepared Whop side-effect fingerprint drifted before execution")
    if current.state != "RESERVED":
        raise RuntimeError("prepared Whop side effect is not in executable RESERVED state")

    def _execute(reservation):
        return execute_reserved_whop_bounty_submission(
            reservation,
            ledger=side_effect_ledger,
            credential_ref=credential_ref,
            credential_provider=credential_provider,
            transport=transport,
        )

    runtime = execute_whop_bounty_job_and_record_provenance(
        verified_job,
        submission.reservation,
        queue=queue,
        worker_id=worker_id,
        now=now,
        binding_ledger=binding_ledger,
        side_effect_ledger=side_effect_ledger,
        provenance_ledger=provenance_ledger,
        execute_submission=_execute,
    )
    return OpenShortsWhopExecutionResult(
        prepared=prepared,
        execution=runtime.execution,
        provenance=runtime.provenance,
    )
