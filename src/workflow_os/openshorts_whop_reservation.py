from __future__ import annotations

import re
from dataclasses import dataclass

from .durable_worker import VerifiedLeasedOpportunityJob
from .openshorts_whop_handoff import PreparedOpenShortsWhopDeliverable
from .side_effects import SideEffectLedger
from .whop_bounty_job_preparation import (
    PreparedDurableWhopBountySubmission,
    prepare_durable_whop_bounty_submission,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PreparedOpenShortsWhopSubmission:
    """Whop reservation bound to one verified OpenShorts output provenance record."""

    submission: PreparedDurableWhopBountySubmission
    openshorts_idempotency_key: str
    openshorts_provider_job_id: str
    openshorts_clip_index: int
    openshorts_evidence_sha256: str


def _verify_render_parent(
    verified_job: VerifiedLeasedOpportunityJob,
    handoff: PreparedOpenShortsWhopDeliverable,
) -> None:
    record = verified_job.job
    if record.job_type == "produce_and_publish":
        if not handoff.openshorts_idempotency_key.startswith(f"openshorts:{record.job_id}:"):
            raise RuntimeError("OpenShorts handoff is not bound to this durable render job")
        return
    if record.job_type != "submit_reward":
        raise RuntimeError("OpenShorts Whop reservation requires an approved durable job type")

    upstream = verified_job.payload.get("upstream_render")
    if not isinstance(upstream, dict):
        raise RuntimeError("submit_reward job is missing upstream render provenance")
    source_job_id = upstream.get("source_job_id")
    source_fingerprint = upstream.get("source_request_fingerprint")
    if not isinstance(source_job_id, int) or isinstance(source_job_id, bool) or source_job_id < 1:
        raise RuntimeError("upstream render source job identity is invalid")
    if not isinstance(source_fingerprint, str) or not _SHA256_RE.fullmatch(source_fingerprint):
        raise RuntimeError("upstream render source fingerprint is malformed")
    if upstream.get("openshorts_idempotency_key") != handoff.openshorts_idempotency_key:
        raise RuntimeError("OpenShorts handoff idempotency provenance drifted")
    if not handoff.openshorts_idempotency_key.startswith(f"openshorts:{source_job_id}:"):
        raise RuntimeError("OpenShorts handoff is not bound to the upstream render job")
    if upstream.get("provider_job_id") != handoff.provider_job_id:
        raise RuntimeError("OpenShorts provider job provenance drifted")
    if upstream.get("clip_index") != handoff.clip_index:
        raise RuntimeError("OpenShorts clip provenance drifted")
    if upstream.get("evidence_sha256") != handoff.evidence_sha256:
        raise RuntimeError("OpenShorts evidence provenance drifted")
    if upstream.get("video_url") not in handoff.deliverable.urls:
        raise RuntimeError("Whop deliverable URL is not the verified upstream render output")


def reserve_verified_openshorts_whop_submission(
    verified_job: VerifiedLeasedOpportunityJob,
    handoff: PreparedOpenShortsWhopDeliverable,
    *,
    credential_authority_verified: bool,
    ledger: SideEffectLedger,
    max_attempts: int = 3,
) -> PreparedOpenShortsWhopSubmission:
    """Reserve Whop submission only when durable job and render provenance agree.

    This boundary performs no network I/O. For dedicated `submit_reward` jobs it
    validates immutable parent-render provenance copied into the child payload,
    rather than incorrectly treating the child job itself as the render job.
    """
    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(handoff, PreparedOpenShortsWhopDeliverable):
        raise TypeError("handoff must be PreparedOpenShortsWhopDeliverable")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")

    record = verified_job.job
    if handoff.opportunity_id != record.opportunity_id:
        raise RuntimeError("OpenShorts handoff opportunity identity drifted")
    if not _SHA256_RE.fullmatch(handoff.evidence_sha256):
        raise RuntimeError("OpenShorts handoff evidence digest is malformed")
    _verify_render_parent(verified_job, handoff)
    if not handoff.provider_job_id.strip():
        raise RuntimeError("OpenShorts provider job identity is missing")
    if handoff.clip_index < 0:
        raise RuntimeError("OpenShorts clip index is invalid")

    submission = prepare_durable_whop_bounty_submission(
        verified_job,
        handoff.deliverable,
        credential_authority_verified=credential_authority_verified,
        deliverable_verified=True,
        ledger=ledger,
        max_attempts=max_attempts,
    )
    if submission.opportunity_id != handoff.opportunity_id:
        raise RuntimeError("Whop reservation opportunity identity drifted")
    if submission.job_id != record.job_id:
        raise RuntimeError("Whop reservation job identity drifted")

    return PreparedOpenShortsWhopSubmission(
        submission=submission,
        openshorts_idempotency_key=handoff.openshorts_idempotency_key,
        openshorts_provider_job_id=handoff.provider_job_id,
        openshorts_clip_index=handoff.clip_index,
        openshorts_evidence_sha256=handoff.evidence_sha256,
    )
