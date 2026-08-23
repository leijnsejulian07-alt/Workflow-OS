from __future__ import annotations

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
    WhopBountySubmissionResult,
    build_workforce_submission_request,
)
from workflow_os.credentials import CredentialProvider, CredentialRef, lease_credential


def submit_whop_bounty_with_credential(
    *,
    bounty_id: str,
    deliverable: WhopBountyDeliverable,
    evidence: WhopBountySubmissionEvidence,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    idempotency_key: str,
    transport: WhopBountyHttpTransport,
) -> WhopBountySubmissionResult:
    """Lease a Whop user token only at the narrow official submission boundary."""

    if not isinstance(credential_ref, CredentialRef):
        raise TypeError("credential_ref must be a CredentialRef")
    if credential_ref.platform != "whop":
        raise ValueError("Whop bounty execution requires a Whop credential reference")
    if credential_ref.secret_name != "user_token":
        raise ValueError("Whop bounty execution requires a user_token credential")
    if not isinstance(transport, WhopBountyHttpTransport):
        raise TypeError("transport must be a WhopBountyHttpTransport")

    lease = lease_credential(credential_provider, credential_ref)
    request = build_workforce_submission_request(
        bounty_id=bounty_id,
        deliverable=deliverable,
        evidence=evidence,
        user_token=lease.reveal(),
        idempotency_key=idempotency_key,
    )
    return transport.submit(request, expected_bounty_id=bounty_id)
