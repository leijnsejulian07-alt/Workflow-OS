from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from workflow_os.adapters.tiktok_credentials import execute_tiktok_direct_post_with_credential
from workflow_os.adapters.tiktok_direct_post import TikTokDirectPostOptions
from workflow_os.adapters.tiktok_direct_post_execution import TikTokPollingPolicy
from workflow_os.adapters.tiktok_http_transport import TikTokHttpTransport
from workflow_os.credentials import CredentialProvider, CredentialRef
from workflow_os.production_reservation_pipeline import PreparedProductionSubmission
from workflow_os.side_effects import SideEffectLedger, SideEffectRecord
from workflow_os.submission_execution import execute_reserved_submission


_TIKTOK_DESTINATION_HOSTS = frozenset({"www.tiktok.com"})


def execute_reserved_tiktok_production_submission(
    prepared: PreparedProductionSubmission,
    *,
    ledger: SideEffectLedger,
    options: TikTokDirectPostOptions,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    asset_root: str | Path,
    transport: TikTokHttpTransport,
    polling: TikTokPollingPolicy = TikTokPollingPolicy(),
    sleep: Callable[[float], None],
) -> SideEffectRecord:
    """Execute one already-verified/reserved production submission through TikTok.

    This is intentionally a thin orchestration boundary. It performs no internal
    retries and never persists credential material. The SideEffectLedger enters
    EXECUTING before the official platform adapter is called and remains the sole
    authority for retry/reconciliation state.
    """

    if not isinstance(prepared, PreparedProductionSubmission):
        raise TypeError("prepared must be PreparedProductionSubmission")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")

    side_effect = prepared.reservation.side_effect
    if not prepared.reservation.decision.allowed or side_effect is None:
        raise RuntimeError("production submission must be allowed and reserved")

    request = prepared.request
    destination = urlparse(request.destination_url)
    if (
        destination.scheme != "https"
        or destination.hostname not in _TIKTOK_DESTINATION_HOSTS
        or destination.username is not None
        or destination.password is not None
    ):
        raise ValueError("reserved production destination is not an approved TikTok origin")

    decision_key = prepared.reservation.decision.idempotency_key
    if not decision_key or decision_key != side_effect.idempotency_key:
        raise RuntimeError("reservation idempotency identity is inconsistent")
    if side_effect.action != "publish_submission":
        raise RuntimeError("reservation is not a publication side effect")
    if side_effect.target != request.destination_url.strip():
        raise RuntimeError("reservation target does not match submission request")

    current = ledger.get(side_effect.idempotency_key)
    if current is None:
        raise RuntimeError("reserved side effect is missing from the supplied ledger")
    if current.request_fingerprint != side_effect.request_fingerprint:
        raise RuntimeError("reserved side-effect fingerprint changed")
    if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
        raise RuntimeError(f"reserved side effect is not executable from state {current.state}")

    return execute_reserved_submission(
        prepared.reservation,
        ledger=ledger,
        submit=lambda: execute_tiktok_direct_post_with_credential(
            request,
            options=options,
            credential_ref=credential_ref,
            credential_provider=credential_provider,
            asset_root=asset_root,
            transport=transport,
            polling=polling,
            sleep=sleep,
        ),
    )
