from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .adapters.whop_bounty_execution import (
    WhopBountyReservation,
    reserve_whop_bounty_submission,
)
from .adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
)
from .durable_worker import VerifiedLeasedOpportunityJob
from .side_effects import SideEffectLedger


_BOUNTY_ID_RE = re.compile(r"^bnty_[A-Za-z0-9_-]{3,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PreparedDurableWhopBountySubmission:
    """Exact reserved submission prepared from one verified durable Whop job."""

    reservation: WhopBountyReservation
    opportunity_id: str
    job_id: int
    job_request_fingerprint: str


def _verified_whop_job(job: VerifiedLeasedOpportunityJob) -> tuple[str, str]:
    if not isinstance(job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    record = job.job
    opportunity = job.opportunity

    if record.job_type != "produce_and_publish":
        raise RuntimeError("Whop preparation requires a produce_and_publish job")
    if opportunity.get("opportunity_id") != record.opportunity_id:
        raise RuntimeError("verified opportunity identity does not match durable job")
    if opportunity.get("source_platform") != "whop_bounties":
        raise RuntimeError("durable opportunity is not a Whop Bounties opportunity")
    bounty_id = opportunity.get("campaign_id")
    if not isinstance(bounty_id, str) or not _BOUNTY_ID_RE.fullmatch(bounty_id.strip()):
        raise RuntimeError("verified Whop opportunity has malformed bounty identity")
    if opportunity.get("bounty_type") != "workforce":
        raise RuntimeError("only Whop workforce bounties are zero-touch executable")
    if opportunity.get("machine_submission_verified") is not True:
        raise RuntimeError("Whop workforce machine submission is not verified")
    if opportunity.get("zero_touch_execution_enabled") is not True:
        raise RuntimeError("Whop workforce zero-touch execution is not enabled")
    if opportunity.get("rights_verification_state") != "VERIFIED":
        raise RuntimeError("Whop workforce rights are not verified")
    if opportunity.get("account_authorized") is not True:
        raise RuntimeError("Whop worker account is not authorized")
    if opportunity.get("worker_identity_verified") is not True:
        raise RuntimeError("Whop worker identity is not verified")
    if opportunity.get("campaign_requirements_verified") is not True:
        raise RuntimeError("Whop campaign requirements are not verified")
    if opportunity.get("deliverable_requirements_verified") is not True:
        raise RuntimeError("Whop deliverable requirements are not verified")

    fingerprint = record.request_fingerprint
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise RuntimeError("durable job request fingerprint is malformed")
    return bounty_id.strip(), fingerprint


def _idempotency_key(job_id: int, request_fingerprint: str) -> str:
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
        raise ValueError("job_id must be a positive integer")
    if not _SHA256_RE.fullmatch(request_fingerprint):
        raise ValueError("job request fingerprint must be lowercase SHA-256")
    digest = hashlib.sha256(
        f"whop-bounty-job\n{job_id}\n{request_fingerprint}".encode("utf-8")
    ).hexdigest()
    return f"whopjob:{job_id}:{digest}"


def prepare_durable_whop_bounty_submission(
    verified_job: VerifiedLeasedOpportunityJob,
    deliverable: WhopBountyDeliverable,
    *,
    deliverable_verified: bool,
    ledger: SideEffectLedger,
    max_attempts: int = 3,
) -> PreparedDurableWhopBountySubmission:
    """Reserve exactly one Whop workforce submission for a verified durable job.

    Opportunity-owned rights/account/worker/campaign evidence comes only from the
    immutable verified job snapshot. The caller may contribute only the final
    deliverable plus an explicit verification result. A deterministic job-bound
    idempotency key ensures that a replay is stable; changing the deliverable for
    the same job conflicts in SideEffectLedger before any network I/O.
    """

    if not isinstance(deliverable, WhopBountyDeliverable):
        raise TypeError("deliverable must be WhopBountyDeliverable")
    if not isinstance(deliverable_verified, bool):
        raise TypeError("deliverable_verified must be a boolean")
    if deliverable_verified is not True:
        raise ValueError("Whop bounty deliverable is not verified")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")

    bounty_id, request_fingerprint = _verified_whop_job(verified_job)
    evidence = WhopBountySubmissionEvidence(
        user_credential_verified=True,
        worker_identity_verified=True,
        rights_verified=True,
        campaign_requirements_verified=True,
        deliverable_verified=True,
    )
    idem = _idempotency_key(verified_job.job.job_id, request_fingerprint)
    reservation = reserve_whop_bounty_submission(
        bounty_id=bounty_id,
        deliverable=deliverable,
        evidence=evidence,
        idempotency_key=idem,
        ledger=ledger,
        max_attempts=max_attempts,
    )
    return PreparedDurableWhopBountySubmission(
        reservation=reservation,
        opportunity_id=verified_job.job.opportunity_id,
        job_id=verified_job.job.job_id,
        job_request_fingerprint=request_fingerprint,
    )
