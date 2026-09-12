from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from .durable_worker import VerifiedLeasedOpportunityJob
from .side_effects import SideEffectLedger, SideEffectRecord

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TARGET = "https://api.openshorts.app/api/process"


@dataclass(frozen=True)
class PreparedOpenShortsProcessing:
    reservation: SideEffectRecord
    opportunity_id: str
    job_id: int
    job_request_fingerprint: str
    source_url: str
    webhook_url: str
    captions: bool
    auto_hook: bool


def _verified_job(job: VerifiedLeasedOpportunityJob) -> tuple[str, str]:
    if not isinstance(job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    record = job.job
    opportunity = job.opportunity
    if record.job_type != "produce_and_publish":
        raise RuntimeError("OpenShorts preparation requires a produce_and_publish job")
    if opportunity.get("opportunity_id") != record.opportunity_id:
        raise RuntimeError("verified opportunity identity does not match durable job")
    if opportunity.get("rights_verification_state") != "VERIFIED":
        raise RuntimeError("OpenShorts source rights are not verified")
    if not str(opportunity.get("usage_rights") or "").strip():
        raise RuntimeError("OpenShorts source usage rights are unclear")
    owner_minutes = opportunity.get("expected_owner_minutes")
    if isinstance(owner_minutes, bool) or not isinstance(owner_minutes, (int, float)):
        raise RuntimeError("OpenShorts owner workload evidence is invalid")
    if not math.isfinite(float(owner_minutes)) or float(owner_minutes) != 0.0:
        raise RuntimeError("OpenShorts execution requires recurring owner work")
    net_profit = opportunity.get("expected_net_profit")
    if isinstance(net_profit, bool) or not isinstance(net_profit, (int, float)):
        raise RuntimeError("OpenShorts economic evidence is invalid")
    if not math.isfinite(float(net_profit)) or float(net_profit) <= 0:
        raise RuntimeError("OpenShorts expected margin is not positive")
    fingerprint = record.request_fingerprint
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise RuntimeError("durable job request fingerprint is malformed")
    return record.opportunity_id, fingerprint


def _idempotency_key(job_id: int, request_fingerprint: str) -> str:
    digest = hashlib.sha256(
        f"openshorts-job\n{job_id}\n{request_fingerprint}".encode("utf-8")
    ).hexdigest()
    return f"openshorts:{job_id}:{digest}"


def prepare_durable_openshorts_processing(
    verified_job: VerifiedLeasedOpportunityJob,
    *,
    source_url: str,
    webhook_url: str,
    credential_authority_verified: bool,
    cost_authority_verified: bool,
    ledger: SideEffectLedger,
    captions: bool = True,
    auto_hook: bool = True,
    max_attempts: int = 2,
) -> PreparedOpenShortsProcessing:
    """Reserve one hosted OpenShorts process call without storing secrets."""
    if credential_authority_verified is not True:
        raise ValueError("OpenShorts credential authority is not verified")
    if cost_authority_verified is not True:
        raise ValueError("OpenShorts provider cost authority is not verified")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("source_url must be a non-empty string")
    if not isinstance(webhook_url, str) or not webhook_url.strip():
        raise ValueError("webhook_url must be a non-empty string")
    if not isinstance(captions, bool) or not isinstance(auto_hook, bool):
        raise TypeError("captions and auto_hook must be booleans")

    opportunity_id, fingerprint = _verified_job(verified_job)
    payload = {
        "opportunity_id": opportunity_id,
        "job_id": verified_job.job.job_id,
        "source_url": source_url.strip(),
        "webhook_url": webhook_url.strip(),
        "captions": captions,
        "auto_hook": auto_hook,
    }
    reservation = ledger.reserve(
        idempotency_key=_idempotency_key(verified_job.job.job_id, fingerprint),
        action="openshorts.process",
        target=_TARGET,
        payload=payload,
        max_attempts=max_attempts,
    )
    return PreparedOpenShortsProcessing(
        reservation=reservation,
        opportunity_id=opportunity_id,
        job_id=verified_job.job.job_id,
        job_request_fingerprint=fingerprint,
        source_url=source_url.strip(),
        webhook_url=webhook_url.strip(),
        captions=captions,
        auto_hook=auto_hook,
    )
