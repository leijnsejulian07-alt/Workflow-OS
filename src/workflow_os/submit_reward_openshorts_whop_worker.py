from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from .credentials import CredentialProvider, CredentialRef
from .durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from .durable_worker import claim_verified_opportunity_job
from .job_queue import JobQueue
from .openshorts_output_provenance import OpenShortsClipOutput, OpenShortsOutputProvenanceStore
from .openshorts_output_qc import OpenShortsOutputQCEvidence, verify_openshorts_output_technical_qc
from .openshorts_whop_execution import OpenShortsWhopExecutionResult, execute_prepared_openshorts_whop_submission
from .openshorts_whop_handoff import prepare_submit_reward_openshorts_whop_deliverable
from .openshorts_whop_reservation import reserve_verified_openshorts_whop_submission
from .side_effects import SideEffectLedger
from .whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger


@dataclass(frozen=True)
class SubmitRewardWorkerResult:
    attempted: bool
    execution: OpenShortsWhopExecutionResult | None


def _bound_output(verified_job, store: OpenShortsOutputProvenanceStore) -> OpenShortsClipOutput:
    upstream = verified_job.payload.get("upstream_render")
    if not isinstance(upstream, dict):
        raise RuntimeError("submit_reward job is missing upstream render provenance")
    key = upstream.get("openshorts_idempotency_key")
    index = upstream.get("clip_index")
    if not isinstance(key, str) or not key or not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise RuntimeError("submit_reward upstream output identity is malformed")
    matches = [item for item in store.list_for(key) if item.clip_index == index]
    if len(matches) != 1:
        raise RuntimeError("submit_reward output is missing immutable OpenShorts provenance")
    return matches[0]


def _authority(verified_job) -> tuple[bool, bool, bool]:
    opportunity = verified_job.opportunity
    return (
        opportunity.get("rights_verification_state") == "VERIFIED",
        opportunity.get("campaign_requirements_verified") is True,
        opportunity.get("disclosure_satisfied") is True,
    )


def run_submit_reward_openshorts_whop_once(
    *,
    queue: JobQueue,
    side_effect_ledger: SideEffectLedger,
    output_store: OpenShortsOutputProvenanceStore,
    binding_ledger: DurableWhopBountyBindingLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    transport: WhopBountyHttpTransport,
    worker_id: str,
    now: str,
    workspace_root: str | Path,
    allowed_download_hosts: Iterable[str],
    openshorts_api_key: str | None = None,
    credential_authority_verified: bool,
    lease_seconds: int = 300,
    max_download_bytes: int = 128 * 1024 * 1024,
    timeout_seconds: int = 30,
    expected_duration_ms: int | None = None,
    require_audio: bool = False,
    caption: str = "",
    qc_verifier: Callable[..., OpenShortsOutputQCEvidence] = verify_openshorts_output_technical_qc,
) -> SubmitRewardWorkerResult:
    """Execute at most one durable OpenShorts-derived Whop reward submission.

    The worker claims only ``submit_reward`` jobs. Before any Whop I/O it resolves
    immutable parent output provenance, downloads/QCs one bounded media asset, and
    rechecks opportunity-owned rights/campaign/disclosure authority. Secrets remain
    runtime-only. Pre-execution failures are returned to the bounded durable queue;
    Whop execution owns its own side-effect/job reconciliation semantics.
    """
    if credential_authority_verified is not True:
        raise ValueError("Whop credential authority is not verified")
    if not isinstance(credential_ref, CredentialRef) or credential_ref.platform != "whop" or credential_ref.secret_name != "user_token":
        raise ValueError("worker requires an account-scoped Whop user_token reference")
    if not callable(qc_verifier):
        raise TypeError("qc_verifier must be callable")

    verified = claim_verified_opportunity_job(
        queue,
        worker_id=worker_id,
        now=now,
        lease_seconds=lease_seconds,
        allowed_job_types={"submit_reward"},
    )
    if verified is None:
        return SubmitRewardWorkerResult(attempted=False, execution=None)

    try:
        output = _bound_output(verified, output_store)
        qc = qc_verifier(
            output,
            store=output_store,
            workspace_root=workspace_root,
            allowed_download_hosts=allowed_download_hosts,
            api_key=openshorts_api_key,
            max_download_bytes=max_download_bytes,
            timeout_seconds=timeout_seconds,
            expected_duration_ms=expected_duration_ms,
            require_audio=require_audio,
        )
        if not isinstance(qc, OpenShortsOutputQCEvidence):
            raise TypeError("qc_verifier must return OpenShortsOutputQCEvidence")
        rights_verified, campaign_verified, disclosure_satisfied = _authority(verified)
        handoff = prepare_submit_reward_openshorts_whop_deliverable(
            verified_job=verified,
            output=output,
            technical_qc=qc,
            rights_verified=rights_verified,
            campaign_requirements_verified=campaign_verified,
            disclosure_satisfied=disclosure_satisfied,
            caption=caption or output.title,
        )
        prepared = reserve_verified_openshorts_whop_submission(
            verified,
            handoff,
            credential_authority_verified=True,
            ledger=side_effect_ledger,
        )
    except Exception:
        queue.fail(
            verified.job.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="submit_reward pre-execution verification failed",
        )
        raise

    execution = execute_prepared_openshorts_whop_submission(
        verified,
        prepared,
        queue=queue,
        worker_id=worker_id,
        now=now,
        binding_ledger=binding_ledger,
        side_effect_ledger=side_effect_ledger,
        credential_ref=credential_ref,
        credential_provider=credential_provider,
        transport=transport,
        provenance_ledger=provenance_ledger,
    )
    return SubmitRewardWorkerResult(attempted=True, execution=execution)
