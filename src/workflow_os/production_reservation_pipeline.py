from __future__ import annotations

from dataclasses import dataclass

from .production_handoff import ProducerOutput
from .production_submission import ProductionSubmissionContext, build_submission_request
from .side_effects import SideEffectLedger
from .submission_execution import SubmissionReservation, reserve_submission
from .submissions import SubmissionAsset, SubmissionDecision, SubmissionRequest, evaluate_submission
from .verified_production import VerifiedProductionResult, verify_production_output


@dataclass(frozen=True)
class PreparedProductionSubmission:
    """One producer output verified, normalized, and safely reserved for publication."""

    verified: VerifiedProductionResult
    request: SubmissionRequest
    reservation: SubmissionReservation


def _build_preflight_request(
    source: ProducerOutput,
    *,
    opportunity_id: str,
    context: ProductionSubmissionContext,
    source_material_rights_verified: bool,
    campaign_requirements_verified: bool,
    disclosure_satisfied: bool,
) -> SubmissionRequest:
    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")
    if not isinstance(context, ProductionSubmissionContext):
        raise ValueError("context must be ProductionSubmissionContext")

    return SubmissionRequest(
        opportunity_id=opportunity_id,
        source_platform=context.source_platform,
        campaign_url=context.campaign_url,
        destination_url=context.destination_url,
        caption=context.caption,
        asset=SubmissionAsset(
            path=source.relative_path,
            media_type=source.media_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
        ),
        rights_verified=source_material_rights_verified is True,
        account_authorized=context.account_authorized is True,
        disclosure_satisfied=disclosure_satisfied is True,
        campaign_requirements_verified=campaign_requirements_verified is True,
    )


def verify_and_reserve_production_submission(
    workspace_root: str,
    source: ProducerOutput,
    *,
    opportunity_id: str,
    campaign_id: str,
    source_material_rights_verified: bool,
    campaign_requirements_verified: bool,
    disclosure_satisfied: bool,
    context: ProductionSubmissionContext,
    allowed_destination_hosts: set[str] | frozenset[str],
    ledger: SideEffectLedger,
    max_attempts: int = 3,
    **probe_kwargs: object,
) -> PreparedProductionSubmission:
    """Fail closed from producer output through QC into a reserved submission.

    The cheap submission gate runs before ffprobe, avoiding expensive local media
    work for requests that already fail rights/account/destination/campaign policy.
    After technical QC and manifest promotion, the final request is re-evaluated.
    Its idempotency key must exactly match the preflight decision before any ledger
    mutation is allowed.
    """

    if not isinstance(ledger, SideEffectLedger):
        raise ValueError("ledger must be SideEffectLedger")
    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or not 1 <= max_attempts <= 10
    ):
        raise ValueError("max_attempts must be between 1 and 10")

    preflight_request = _build_preflight_request(
        source,
        opportunity_id=opportunity_id,
        context=context,
        source_material_rights_verified=source_material_rights_verified,
        campaign_requirements_verified=campaign_requirements_verified,
        disclosure_satisfied=disclosure_satisfied,
    )
    preflight: SubmissionDecision = evaluate_submission(
        preflight_request,
        allowed_destination_hosts=allowed_destination_hosts,
    )
    if not preflight.allowed or preflight.idempotency_key is None:
        raise ValueError(f"submission preflight rejected: {preflight.reason}")

    verified = verify_production_output(
        workspace_root,
        source,
        opportunity_id=opportunity_id,
        campaign_id=campaign_id,
        source_material_rights_verified=source_material_rights_verified,
        campaign_requirements_verified=campaign_requirements_verified,
        disclosure_satisfied=disclosure_satisfied,
        **probe_kwargs,
    )
    request = build_submission_request(verified.manifest, context)
    final_decision = evaluate_submission(
        request,
        allowed_destination_hosts=allowed_destination_hosts,
    )
    if not final_decision.allowed or final_decision.idempotency_key is None:
        raise RuntimeError(
            f"verified submission unexpectedly rejected: {final_decision.reason}"
        )
    if final_decision.idempotency_key != preflight.idempotency_key:
        raise RuntimeError("verified submission changed publication identity after preflight")

    reservation = reserve_submission(
        request,
        allowed_destination_hosts=allowed_destination_hosts,
        ledger=ledger,
        max_attempts=max_attempts,
    )
    if reservation.side_effect is None:
        raise RuntimeError("verified submission was not reserved")
    return PreparedProductionSubmission(
        verified=verified,
        request=request,
        reservation=reservation,
    )
