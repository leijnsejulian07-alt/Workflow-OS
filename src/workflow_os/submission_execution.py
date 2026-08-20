from __future__ import annotations

from dataclasses import dataclass

from workflow_os.side_effects import SideEffectLedger, SideEffectRecord
from workflow_os.submissions import SubmissionDecision, SubmissionRequest, evaluate_submission


@dataclass(frozen=True)
class SubmissionReservation:
    decision: SubmissionDecision
    side_effect: SideEffectRecord | None


def reserve_submission(
    request: SubmissionRequest,
    *,
    allowed_destination_hosts: set[str] | frozenset[str],
    ledger: SideEffectLedger,
    max_attempts: int = 3,
) -> SubmissionReservation:
    """Validate submission evidence and reserve the external side effect.

    This is the mandatory bridge between the pure submission readiness gate and
    any future official platform adapter. It performs no network or upload work.
    A denied request never touches the SideEffectLedger. An allowed request is
    reserved with the gate-derived idempotency key before execution can begin.
    """

    decision = evaluate_submission(
        request,
        allowed_destination_hosts=allowed_destination_hosts,
    )
    if not decision.allowed or decision.idempotency_key is None:
        return SubmissionReservation(decision=decision, side_effect=None)

    payload = {
        "opportunity_id": request.opportunity_id.strip(),
        "source_platform": request.source_platform.strip(),
        "campaign_url": request.campaign_url.strip(),
        "destination_url": request.destination_url.strip(),
        "caption": request.caption,
        "asset": {
            "path": request.asset.path.strip(),
            "media_type": request.asset.media_type,
            "size_bytes": request.asset.size_bytes,
            "sha256": request.asset.sha256.strip().lower(),
        },
    }
    record = ledger.reserve(
        idempotency_key=decision.idempotency_key,
        action="publish_submission",
        target=request.destination_url.strip(),
        payload=payload,
        max_attempts=max_attempts,
    )
    return SubmissionReservation(decision=decision, side_effect=record)
