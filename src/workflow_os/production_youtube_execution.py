from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from workflow_os.adapters.youtube_credentials import execute_youtube_upload_with_credential
from workflow_os.adapters.youtube_http_transport import YouTubeHttpTransport
from workflow_os.adapters.youtube_upload import YouTubeUploadOptions
from workflow_os.adapters.youtube_upload_execution import YouTubePollingPolicy
from workflow_os.credentials import CredentialProvider, CredentialRef
from workflow_os.production_reservation_pipeline import PreparedProductionSubmission
from workflow_os.side_effects import SideEffectLedger, SideEffectRecord
from workflow_os.submission_execution import execute_reserved_submission

_YOUTUBE_DESTINATION_HOSTS = frozenset({"www.youtube.com", "youtube.com"})
_MAX_YOUTUBE_ACCOUNT_ID_CHARS = 256


def _clean_account_identity(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > _MAX_YOUTUBE_ACCOUNT_ID_CHARS
        or any(ch.isspace() for ch in cleaned)
        or any(ord(ch) < 33 or ord(ch) == 127 for ch in cleaned)
    ):
        raise ValueError(f"{field} is missing or malformed")
    return cleaned


def execute_reserved_youtube_production_submission(
    prepared: PreparedProductionSubmission,
    *,
    ledger: SideEffectLedger,
    options: YouTubeUploadOptions,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    asset_root: str | Path,
    transport: YouTubeHttpTransport,
    polling: YouTubePollingPolicy = YouTubePollingPolicy(),
    sleep: Callable[[float], None],
    chunk_size: int = 8 * 1024 * 1024,
) -> SideEffectRecord:
    """Execute one verified/reserved production submission through official YouTube APIs."""
    if not isinstance(prepared, PreparedProductionSubmission):
        raise TypeError("prepared must be PreparedProductionSubmission")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")

    verified_account_id = _clean_account_identity(
        options.project_evidence.verified_account_id, "verified YouTube account identity"
    )
    request_account_id = _clean_account_identity(
        prepared.request.account_identity, "reserved YouTube account identity"
    )
    credential_account_id = _clean_account_identity(
        credential_ref.account_id, "YouTube credential account identity"
    )
    if len({verified_account_id, request_account_id, credential_account_id}) != 1:
        raise ValueError("YouTube account identity binding mismatch")

    side_effect = prepared.reservation.side_effect
    if not prepared.reservation.decision.allowed or side_effect is None:
        raise RuntimeError("production submission must be allowed and reserved")

    request = prepared.request
    destination = urlparse(request.destination_url)
    if (
        destination.scheme != "https"
        or destination.hostname not in _YOUTUBE_DESTINATION_HOSTS
        or destination.username is not None
        or destination.password is not None
        or destination.port not in (None, 443)
    ):
        raise ValueError("reserved production destination is not an approved YouTube origin")

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
        submit=lambda: execute_youtube_upload_with_credential(
            request,
            options=options,
            credential_ref=credential_ref,
            credential_provider=credential_provider,
            asset_root=asset_root,
            transport=transport,
            polling=polling,
            sleep=sleep,
            chunk_size=chunk_size,
        ),
    )
