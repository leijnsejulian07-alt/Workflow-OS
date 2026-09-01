import unittest
from unittest.mock import patch

from workflow_os.adapters.youtube_credentials import execute_youtube_upload_with_credential
from workflow_os.adapters.youtube_upload import YouTubeProjectEvidence, YouTubeUploadOptions
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.submission_execution import SubmissionAttemptResult
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


class Provider:
    def __init__(self):
        self.refs = []
    def lease(self, ref):
        self.refs.append(ref)
        return CredentialLease("leased-token")


def request():
    return SubmissionRequest(
        opportunity_id="opp", source_platform="owned_media", campaign_url="https://www.youtube.com/",
        destination_url="https://www.youtube.com/upload", caption="Caption",
        asset=SubmissionAsset(path="video.mp4", media_type="video/mp4", size_bytes=4, sha256="a" * 64),
        rights_verified=True, account_authorized=True, disclosure_satisfied=True, campaign_requirements_verified=True,
    )


def options():
    return YouTubeUploadOptions(
        title="Title", description="Description", category_id="22", category_id_verified=True,
        privacy_status="private", self_declared_made_for_kids=False,
        project_evidence=YouTubeProjectEvidence(True, True, True),
    )


class YouTubeCredentialTests(unittest.TestCase):
    @patch("workflow_os.adapters.youtube_credentials.execute_youtube_upload_attempt")
    def test_leases_secret_only_at_execution_boundary(self, execute_mock):
        execute_mock.return_value = SubmissionAttemptResult(outcome="UNKNOWN")
        provider = Provider()
        ref = CredentialRef("youtube", "acct-1", "access_token")
        result = execute_youtube_upload_with_credential(
            request(), options=options(), credential_ref=ref, credential_provider=provider,
            asset_root=".", transport=object(), sleep=lambda _: None,
        )
        self.assertEqual(result.outcome, "UNKNOWN")
        self.assertEqual(provider.refs, [ref])
        self.assertEqual(execute_mock.call_args.kwargs["access_token"], "leased-token")

    def test_rejects_non_youtube_credential_before_leasing(self):
        provider = Provider()
        with self.assertRaisesRegex(ValueError, "YouTube credential"):
            execute_youtube_upload_with_credential(
                request(), options=options(), credential_ref=CredentialRef("tiktok", "acct-1", "access_token"),
                credential_provider=provider, asset_root=".", transport=object(), sleep=lambda _: None,
            )
        self.assertEqual(provider.refs, [])


if __name__ == "__main__":
    unittest.main()
