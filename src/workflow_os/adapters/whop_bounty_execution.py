from __future__ import annotations

from dataclasses import dataclass

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.adapters.whop_bounty_submission import (
    WHOP_BOUNTY_SUBMISSION_URL,
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
    WhopBountySubmissionResult,
    build_workforce_submission_request,
)
from workflow_os.credentials import CredentialProvider, CredentialRef, lease_credential
from workflow_os.side_effects import SideEffectLedger, SideEffectRecord


_ACTION = "submit_whop_bounty"
_VALIDATION_TOKEN = "workflow-os-validation-placeholder"


@dataclass(frozen=True)
class WhopBountyReservation:
    bounty_id: str
    deliverable: WhopBountyDeliverable
    evidence: WhopBountySubmissionEvidence
    idempotency_key: str
    side_effect: SideEffectRecord


def _validated_payload(
    *,
    bounty_id: str,
    deliverable: WhopBountyDeliverable,
    evidence: WhopBountySubmissionEvidence,
    idempotency_key: str,
) -> dict[str, object]:
    """Reuse the pure request builder for validation without persisting a credential."""

    request = build_workforce_submission_request(
        bounty_id=bounty_id,
        deliverable=deliverable,
        evidence=evidence,
        user_token=_VALIDATION_TOKEN,
        idempotency_key=idempotency_key,
    )
    return {
        "bounty_id": request.json_body["bounty_id"],
        "deliverable": request.json_body["deliverable"],
        "evidence": {
            "user_credential_verified": evidence.user_credential_verified,
            "worker_identity_verified": evidence.worker_identity_verified,
            "rights_verified": evidence.rights_verified,
            "campaign_requirements_verified": evidence.campaign_requirements_verified,
            "deliverable_verified": evidence.deliverable_verified,
        },
    }


def reserve_whop_bounty_submission(
    *,
    bounty_id: str,
    deliverable: WhopBountyDeliverable,
    evidence: WhopBountySubmissionEvidence,
    idempotency_key: str,
    ledger: SideEffectLedger,
    max_attempts: int = 3,
) -> WhopBountyReservation:
    """Validate and durably reserve one exact Whop bounty submission before I/O."""

    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be a SideEffectLedger")

    payload = _validated_payload(
        bounty_id=bounty_id,
        deliverable=deliverable,
        evidence=evidence,
        idempotency_key=idempotency_key,
    )
    record = ledger.reserve(
        idempotency_key=idempotency_key,
        action=_ACTION,
        target=WHOP_BOUNTY_SUBMISSION_URL,
        payload=payload,
        max_attempts=max_attempts,
    )
    return WhopBountyReservation(
        bounty_id=str(payload["bounty_id"]),
        deliverable=deliverable,
        evidence=evidence,
        idempotency_key=idempotency_key.strip(),
        side_effect=record,
    )


def execute_reserved_whop_bounty_submission(
    reservation: WhopBountyReservation,
    *,
    ledger: SideEffectLedger,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    transport: WhopBountyHttpTransport,
) -> SideEffectRecord:
    """Execute one reserved Whop bounty attempt and reconcile from confirmed truth.

    Credential resolution and request construction happen before the ledger enters
    EXECUTING so local validation/secret-provider failures cannot create an
    ambiguous external state. The complete non-secret payload is rebound against
    the persisted reservation immediately before execution, preventing post-
    reservation identity drift. Once EXECUTING begins, every exception is treated
    as UNKNOWN because the transport may have dispatched the request. Only a
    confirmed 201/submitted response may mark the side effect SUCCEEDED.
    """

    if not isinstance(reservation, WhopBountyReservation):
        raise TypeError("reservation must be a WhopBountyReservation")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be a SideEffectLedger")
    if not isinstance(credential_ref, CredentialRef):
        raise TypeError("credential_ref must be a CredentialRef")
    if credential_ref.platform != "whop" or credential_ref.secret_name != "user_token":
        raise ValueError("Whop bounty execution requires an account-scoped Whop user_token")
    if not isinstance(transport, WhopBountyHttpTransport):
        raise TypeError("transport must be a WhopBountyHttpTransport")

    current = ledger.get(reservation.idempotency_key)
    if current is None:
        raise RuntimeError("Whop bounty reservation is missing from the side-effect ledger")
    if current.action != _ACTION or current.target != WHOP_BOUNTY_SUBMISSION_URL:
        raise RuntimeError("Whop bounty reservation is bound to the wrong side effect")
    if current.request_fingerprint != reservation.side_effect.request_fingerprint:
        raise RuntimeError("Whop bounty reservation fingerprint drifted")

    rebound_payload = _validated_payload(
        bounty_id=reservation.bounty_id,
        deliverable=reservation.deliverable,
        evidence=reservation.evidence,
        idempotency_key=reservation.idempotency_key,
    )
    rebound = ledger.reserve(
        idempotency_key=reservation.idempotency_key,
        action=_ACTION,
        target=WHOP_BOUNTY_SUBMISSION_URL,
        payload=rebound_payload,
        max_attempts=current.max_attempts,
    )
    if rebound.request_fingerprint != current.request_fingerprint:
        raise RuntimeError("Whop bounty reservation payload drifted")

    lease = lease_credential(credential_provider, credential_ref)
    request = build_workforce_submission_request(
        bounty_id=reservation.bounty_id,
        deliverable=reservation.deliverable,
        evidence=reservation.evidence,
        user_token=lease.reveal(),
        idempotency_key=reservation.idempotency_key,
    )

    ledger.begin_attempt(reservation.idempotency_key)
    try:
        result: WhopBountySubmissionResult = transport.submit(
            request,
            expected_bounty_id=reservation.bounty_id,
        )
    except Exception:
        ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
        raise

    try:
        return ledger.mark_succeeded(
            reservation.idempotency_key,
            external_reference=result.submission_id,
        )
    except Exception:
        latest = ledger.get(reservation.idempotency_key)
        if latest is not None and latest.state == "EXECUTING":
            ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
        raise
