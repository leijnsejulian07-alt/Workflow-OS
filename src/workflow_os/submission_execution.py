from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from workflow_os.side_effects import SideEffectLedger, SideEffectRecord
from workflow_os.submissions import SubmissionDecision, SubmissionRequest, evaluate_submission


@dataclass(frozen=True)
class SubmissionReservation:
    decision: SubmissionDecision
    side_effect: SideEffectRecord | None


@dataclass(frozen=True)
class SubmissionAttemptResult:
    """Bounded result contract returned by an official platform adapter.

    APPLIED means the platform has confirmed the submission and must include a
    stable external reference. NOT_APPLIED is only for evidence that proves no
    external side effect occurred. UNKNOWN is required for timeouts, connection
    loss after request dispatch, malformed responses, or any other ambiguous
    outcome that must not be blindly retried.
    """

    outcome: Literal["APPLIED", "NOT_APPLIED", "UNKNOWN"]
    external_reference: str | None = None


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


def execute_reserved_submission(
    reservation: SubmissionReservation,
    *,
    ledger: SideEffectLedger,
    submit: Callable[[], SubmissionAttemptResult],
) -> SideEffectRecord:
    """Execute one already-reserved platform attempt with fail-closed recovery.

    The ledger enters EXECUTING before calling the adapter. Exceptions and any
    ambiguous/invalid adapter result become UNKNOWN so Workflow OS cannot retry
    blindly. A retryable failure is accepted only when the adapter explicitly
    proves that no external side effect was applied.
    """

    if not reservation.decision.allowed or reservation.side_effect is None:
        raise RuntimeError("submission must be allowed and reserved before execution")

    key = reservation.side_effect.idempotency_key
    ledger.begin_attempt(key)

    try:
        result = submit()
    except Exception:
        ledger.mark_failed(key, definitely_not_applied=False)
        raise

    if not isinstance(result, SubmissionAttemptResult):
        ledger.mark_failed(key, definitely_not_applied=False)
        raise TypeError("platform adapter returned an invalid submission result")

    if result.outcome == "APPLIED":
        reference = result.external_reference.strip() if isinstance(result.external_reference, str) else ""
        if not reference:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("APPLIED submission result requires an external reference")
        try:
            return ledger.mark_succeeded(key, external_reference=reference)
        except Exception:
            current = ledger.get(key)
            if current is not None and current.state == "EXECUTING":
                ledger.mark_failed(key, definitely_not_applied=False)
            raise

    if result.outcome == "NOT_APPLIED":
        if result.external_reference is not None:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("NOT_APPLIED submission result cannot include an external reference")
        return ledger.mark_failed(key, definitely_not_applied=True)

    if result.outcome == "UNKNOWN":
        if result.external_reference is not None:
            ledger.mark_failed(key, definitely_not_applied=False)
            raise ValueError("UNKNOWN submission result cannot include an external reference")
        return ledger.mark_failed(key, definitely_not_applied=False)

    ledger.mark_failed(key, definitely_not_applied=False)
    raise ValueError("unsupported submission outcome")
