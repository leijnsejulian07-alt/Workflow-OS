from __future__ import annotations

from pathlib import Path
from typing import Callable

from workflow_os.adapters.youtube_http_transport import YouTubeHttpTransport
from workflow_os.adapters.youtube_upload import YouTubeUploadOptions
from workflow_os.adapters.youtube_upload_execution import YouTubePollingPolicy, execute_youtube_upload_attempt
from workflow_os.credentials import CredentialProvider, CredentialRef, lease_credential
from workflow_os.submission_execution import SubmissionAttemptResult
from workflow_os.submissions import SubmissionRequest


def execute_youtube_upload_with_credential(
    request: SubmissionRequest,
    *,
    options: YouTubeUploadOptions,
    credential_ref: CredentialRef,
    credential_provider: CredentialProvider,
    asset_root: str | Path,
    transport: YouTubeHttpTransport,
    polling: YouTubePollingPolicy = YouTubePollingPolicy(),
    sleep: Callable[[float], None],
    chunk_size: int = 8 * 1024 * 1024,
) -> SubmissionAttemptResult:
    """Lease an account-scoped YouTube token only for one bounded upload attempt."""
    if not isinstance(credential_ref, CredentialRef):
        raise TypeError("credential_ref must be a CredentialRef")
    if credential_ref.platform != "youtube":
        raise ValueError("YouTube execution requires a YouTube credential reference")
    if credential_ref.secret_name != "access_token":
        raise ValueError("YouTube execution requires an access_token credential")

    lease = lease_credential(credential_provider, credential_ref)
    return execute_youtube_upload_attempt(
        request,
        options=options,
        access_token=lease.reveal(),
        asset_root=asset_root,
        transport=transport,
        polling=polling,
        sleep=sleep,
        chunk_size=chunk_size,
    )
