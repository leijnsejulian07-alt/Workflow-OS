from __future__ import annotations

from dataclasses import dataclass

from .adapters.whop_bounty_submission import WhopBountyDeliverable
from .openshorts_job_preparation import PreparedOpenShortsProcessing
from .openshorts_output_provenance import OpenShortsClipOutput


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


def prepare_openshorts_whop_deliverable(
    *,
    processing: PreparedOpenShortsProcessing,
    output: OpenShortsClipOutput,
    evidence: OpenShortsWhopHandoffEvidence,
    caption: str = "",
) -> PreparedOpenShortsWhopDeliverable:
    """Promote one verified OpenShorts output into a Whop submission candidate.

    This is a no-I/O boundary. It does not submit to Whop and does not infer
    rights, campaign compliance, disclosure, or QC from provider completion.
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
    if not isinstance(caption, str):
        raise TypeError("caption must be a string")
    clean_caption = caption.strip()
    if len(clean_caption) > 4000 or any(ord(ch) < 32 and ch not in "\t\n" for ch in clean_caption):
        raise ValueError("caption is invalid")

    deliverable = WhopBountyDeliverable(
        deliverable_type="content_url",
        urls=(output.video_url,),
        caption=clean_caption,
    )
    return PreparedOpenShortsWhopDeliverable(
        opportunity_id=processing.opportunity_id,
        openshorts_idempotency_key=output.idempotency_key,
        provider_job_id=output.provider_job_id,
        clip_index=output.clip_index,
        evidence_sha256=output.evidence_sha256,
        deliverable=deliverable,
    )
