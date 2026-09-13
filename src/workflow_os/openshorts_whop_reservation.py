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


def reserve_verified_openshorts_whop_submission(
    verified_job: VerifiedLeasedOpportunityJob,
    handoff: PreparedOpenShortsWhopDeliverable,
    *,
    credential_authority_verified: bool,
    ledger: SideEffectLedger,
    max_attempts: int = 3,
) -> PreparedOpenShortsWhopSubmission:
    """Reserve Whop submission only when durable job and render provenance agree.

    This boundary performs no network I/O. It prevents a verified OpenShorts clip
    from being attached to a different durable opportunity/job before the existing
    Whop side-effect reservation and execution path takes over.
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
    if not handoff.openshorts_idempotency_key.startswith(f"openshorts:{record.job_id}:"):
        raise RuntimeError("OpenShorts handoff is not bound to this durable job")
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
