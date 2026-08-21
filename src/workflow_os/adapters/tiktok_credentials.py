from __future__ import annotations

from pathlib import Path
from typing import Callable

from workflow_os.adapters.tiktok_direct_post import TikTokDirectPostOptions
from workflow_os.adapters.tiktok_direct_post_execution import (
    TikTokPollingPolicy,
    execute_tiktok_direct_post_attempt,
)
from workflow_os.adapters.tiktok_http_transport import TikTokHttpTransport
from workflow_os.credentials import CredentialProvider, CredentialRef, lease_credential
from workflow_os.submission_execution import SubmissionAttemptResult
from workflow_os.submissions import SubmissionRequest


def execute_tiktok_direct_post_with_credential(
    request: SubmissionRequest,
    *,
    options: TikTokDirectPostOptions,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    asset_root: str | Path,
    transport: TikTokHttpTransport,
    polling: TikTokPollingPolicy = TikTokPollingPolicy(),
    sleep: Callable[[float], None],
) -> SubmissionAttemptResult:
    """Resolve TikTok access only at execution time and keep references account-scoped.

    The credential value is never added to SubmissionRequest, SideEffectLedger payloads,
    audit records or persisted state. This wrapper only reveals it to the already-bounded
    TikTok request builder for the duration of one execution attempt.
    """

    if not isinstance(credential_ref, CredentialRef):
        raise TypeError("credential_ref must be a CredentialRef")
    if credential_ref.platform != "tiktok":
        raise ValueError("TikTok execution requires a TikTok credential reference")
    if credential_ref.secret_name != "access_token":
        raise ValueError("TikTok execution requires an access_token credential")

    lease = lease_credential(credential_provider, credential_ref)
    return execute_tiktok_direct_post_attempt(
        request,
        options=options,
        access_token=lease.reveal(),
        asset_root=asset_root,
        transport=transport,
        polling=polling,
        sleep=sleep,
    )
