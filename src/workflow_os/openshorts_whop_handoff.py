from __future__ import annotations

from dataclasses import dataclass

from .adapters.whop_bounty_submission import WhopBountyDeliverable
from .durable_worker import VerifiedLeasedOpportunityJob
from .openshorts_job_preparation import PreparedOpenShortsProcessing
from .openshorts_output_provenance import OpenShortsClipOutput
from .openshorts_output_qc import OpenShortsOutputQCEvidence


@dataclass(frozen=True)
class OpenShortsWhopHandoffEvidence:
    rights_verified: bool
    campaign_requirements_verified: bool
    disclosure_satisfied: bool
    qc_passed: bool


@dataclass(frozen=True)
class PreparedOpenShortsWhopDeliverable:
    opportunity_id: str
    openshorts_idempotency_key: str
    provider_job_id: str
    clip_index: int
    evidence_sha256: str
    deliverable: WhopBountyDeliverable


def _caption(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("caption must be a string")
    clean = value.strip()
    if len(clean) > 4000 or any(ord(ch) < 32 and ch not in "\t\n" for ch in clean):
        raise ValueError("caption is invalid")
    return clean


def _deliverable(*, opportunity_id: str, output: OpenShortsClipOutput, caption: str) -> PreparedOpenShortsWhopDeliverable:
    deliverable = WhopBountyDeliverable(
        deliverable_type="content_url",
        urls=(output.video_url,),
        caption=_caption(caption),
    )
    return PreparedOpenShortsWhopDeliverable(
        opportunity_id=opportunity_id,
        openshorts_idempotency_key=output.idempotency_key,
        provider_job_id=output.provider_job_id,
        clip_index=output.clip_index,
        evidence_sha256=output.evidence_sha256,
        deliverable=deliverable,
    )


def prepare_openshorts_whop_deliverable(
    *,
    processing: PreparedOpenShortsProcessing,
    output: OpenShortsClipOutput,
    evidence: OpenShortsWhopHandoffEvidence,
    caption: str = "",
) -> PreparedOpenShortsWhopDeliverable:
    """Promote one verified OpenShorts output into a Whop submission candidate.

    This is the legacy render-job boundary. New dedicated ``submit_reward`` jobs
    must use :func:`prepare_submit_reward_openshorts_whop_deliverable` so technical
    QC is cryptographically bound rather than represented by a caller-supplied bool.
    """
    if not isinstance(processing, PreparedOpenShortsProcessing):
        raise TypeError("processing must be PreparedOpenShortsProcessing")
    if not isinstance(output, OpenShortsClipOutput):
        raise TypeError("output must be OpenShortsClipOutput")
    if not isinstance(evidence, OpenShortsWhopHandoffEvidence):
        raise TypeError("evidence must be OpenShortsWhopHandoffEvidence")

    if output.idempotency_key != processing.reservation.idempotency_key:
        raise RuntimeError("OpenShorts output is not bound to this processing reservation")
    if processing.reservation.action != "openshorts.process":
        raise RuntimeError("processing reservation is not an OpenShorts side effect")
    if processing.reservation.state != "SUCCEEDED":
        raise RuntimeError("OpenShorts processing is not durably confirmed SUCCEEDED")
    if processing.reservation.external_reference != output.provider_job_id:
        raise RuntimeError("OpenShorts provider job identity drifted")

    required = (
        evidence.rights_verified,
        evidence.campaign_requirements_verified,
        evidence.disclosure_satisfied,
        evidence.qc_passed,
    )
    if not all(flag is True for flag in required):
        raise ValueError("OpenShorts-to-Whop handoff evidence is incomplete")
    return _deliverable(opportunity_id=processing.opportunity_id, output=output, caption=caption)


def prepare_submit_reward_openshorts_whop_deliverable(
    *,
    verified_job: VerifiedLeasedOpportunityJob,
    output: OpenShortsClipOutput,
    technical_qc: OpenShortsOutputQCEvidence,
    rights_verified: bool,
    campaign_requirements_verified: bool,
    disclosure_satisfied: bool,
    caption: str = "",
) -> PreparedOpenShortsWhopDeliverable:
    """Build a child-job Whop handoff bound to immutable render and technical-QC evidence.

    This boundary performs no network I/O and grants no rights/compliance authority.
    The three non-technical approvals remain independent fail-closed inputs. Unlike
    the legacy render-job path, QC cannot be asserted with a naked boolean: the
    exact provider output identity and provider evidence digest must match the
    bounded technical-QC record produced from the downloaded media bytes.
    """
    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if verified_job.job.job_type != "submit_reward":
        raise RuntimeError("dedicated OpenShorts Whop handoff requires a submit_reward job")
    if not isinstance(output, OpenShortsClipOutput):
        raise TypeError("output must be OpenShortsClipOutput")
    if not isinstance(technical_qc, OpenShortsOutputQCEvidence):
        raise TypeError("technical_qc must be OpenShortsOutputQCEvidence")
    if not all(flag is True for flag in (rights_verified, campaign_requirements_verified, disclosure_satisfied)):
        raise ValueError("OpenShorts-to-Whop rights/compliance evidence is incomplete")

    upstream = verified_job.payload.get("upstream_render")
    if not isinstance(upstream, dict):
        raise RuntimeError("submit_reward job is missing upstream render provenance")
    if upstream.get("openshorts_idempotency_key") != output.idempotency_key:
        raise RuntimeError("submit_reward output idempotency provenance drifted")
    if upstream.get("provider_job_id") != output.provider_job_id:
        raise RuntimeError("submit_reward provider job provenance drifted")
    if upstream.get("clip_index") != output.clip_index:
        raise RuntimeError("submit_reward clip provenance drifted")
    if upstream.get("evidence_sha256") != output.evidence_sha256:
        raise RuntimeError("submit_reward provider evidence provenance drifted")
    if upstream.get("video_url") != output.video_url:
        raise RuntimeError("submit_reward video URL provenance drifted")

    qc_identity = (
        technical_qc.idempotency_key,
        technical_qc.provider_job_id,
        technical_qc.clip_index,
        technical_qc.provider_evidence_sha256,
    )
    output_identity = (
        output.idempotency_key,
        output.provider_job_id,
        output.clip_index,
        output.evidence_sha256,
    )
    if qc_identity != output_identity:
        raise RuntimeError("technical QC is not bound to the exact OpenShorts output")
    if technical_qc.size_bytes < 1 or not technical_qc.media_sha256:
        raise RuntimeError("technical QC media evidence is incomplete")

    return _deliverable(
        opportunity_id=verified_job.job.opportunity_id,
        output=output,
        caption=caption,
    )
