import tempfile
import unittest
from unittest.mock import patch

from workflow_os.adapters.youtube_upload import YouTubeProjectEvidence, YouTubeUploadOptions
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.production_reservation_pipeline import PreparedProductionSubmission
from workflow_os.production_youtube_execution import execute_reserved_youtube_production_submission
from workflow_os.side_effects import SideEffectLedger
from workflow_os.submission_execution import SubmissionAttemptResult, reserve_submission
from workflow_os.submissions import SubmissionAsset, SubmissionRequest

DIGEST = "a" * 64


def request(destination_url="https://www.youtube.com/upload"):
    return SubmissionRequest(
        opportunity_id="opp-yt-1", source_platform="owned_media",
        campaign_url="https://www.youtube.com/", destination_url=destination_url,
        caption="Caption", asset=SubmissionAsset(path="video.mp4", media_type="video/mp4", size_bytes=4, sha256=DIGEST),
        rights_verified=True, account_authorized=True, disclosure_satisfied=True, campaign_requirements_verified=True,
        account_identity="acct-1",
    )


def options():
    return YouTubeUploadOptions(
        title="Title", description="Description", category_id="22", category_id_verified=True,
        privacy_status="private", self_declared_made_for_kids=False,
        project_evidence=YouTubeProjectEvidence(True, True, True, verified_account_id="acct-1"),
    )


class Provider:
    def lease(self, ref):
        return CredentialLease("secret-token")


class ReservedYouTubeProductionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(f"{self.tempdir.name}/side-effects.sqlite3")
        self.request = request()
        reservation = reserve_submission(self.request, allowed_destination_hosts={"www.youtube.com"}, ledger=self.ledger)
        self.prepared = PreparedProductionSubmission(verified=None, request=self.request, reservation=reservation)
        self.kwargs = dict(
            ledger=self.ledger, options=options(), credential_ref=CredentialRef("youtube", "acct-1", "access_token"),
            credential_provider=Provider(), asset_root=self.tempdir.name, transport=object(), sleep=lambda _: None,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_confirmed_upload_marks_side_effect_succeeded(self, execute_mock):
        execute_mock.return_value = SubmissionAttemptResult(outcome="APPLIED", external_reference="youtube:abc123")
        result = execute_reserved_youtube_production_submission(self.prepared, **self.kwargs)
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertEqual(result.external_reference, "youtube:abc123")
        self.assertEqual(result.attempt_count, 1)

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_unknown_upload_marks_side_effect_unknown(self, execute_mock):
        execute_mock.return_value = SubmissionAttemptResult(outcome="UNKNOWN")
        result = execute_reserved_youtube_production_submission(self.prepared, **self.kwargs)
        self.assertEqual(result.state, "UNKNOWN")
        self.assertEqual(result.attempt_count, 1)

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_foreign_destination_fails_before_execution(self, execute_mock):
        evil = request("https://evil.example/upload")
        reservation = reserve_submission(evil, allowed_destination_hosts={"evil.example"}, ledger=self.ledger)
        prepared = PreparedProductionSubmission(verified=None, request=evil, reservation=reservation)
        with self.assertRaisesRegex(ValueError, "approved YouTube origin"):
            execute_reserved_youtube_production_submission(prepared, **self.kwargs)
        self.assertEqual(reservation.side_effect.state, "RESERVED")
        execute_mock.assert_not_called()

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_foreign_ledger_fails_before_execution(self, execute_mock):
        foreign = SideEffectLedger(f"{self.tempdir.name}/foreign.sqlite3")
        with self.assertRaisesRegex(RuntimeError, "missing from the supplied ledger"):
            execute_reserved_youtube_production_submission(self.prepared, **{**self.kwargs, "ledger": foreign})
        execute_mock.assert_not_called()

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_mismatched_credential_account_fails_before_execution(self, execute_mock):
        kwargs = {**self.kwargs, "credential_ref": CredentialRef("youtube", "acct-2", "access_token")}
        with self.assertRaisesRegex(ValueError, "identity binding mismatch"):
            execute_reserved_youtube_production_submission(self.prepared, **kwargs)
        execute_mock.assert_not_called()

    @patch("workflow_os.production_youtube_execution.execute_youtube_upload_with_credential")
    def test_missing_verified_account_identity_fails_before_execution(self, execute_mock):
        bad_options = YouTubeUploadOptions(
            title="Title", description="Description", category_id="22", category_id_verified=True,
            privacy_status="private", self_declared_made_for_kids=False,
            project_evidence=YouTubeProjectEvidence(True, True, True),
        )
        with self.assertRaisesRegex(ValueError, "verified YouTube account identity"):
            execute_reserved_youtube_production_submission(self.prepared, **{**self.kwargs, "options": bad_options})
        execute_mock.assert_not_called()

    def test_account_identity_participates_in_reservation_identity(self):
        other = request()
        other = SubmissionRequest(**{**other.__dict__, "account_identity": "acct-2"})
        reservation = reserve_submission(other, allowed_destination_hosts={"www.youtube.com"}, ledger=self.ledger)
        self.assertNotEqual(
            self.prepared.reservation.decision.idempotency_key,
            reservation.decision.idempotency_key,
        )


if __name__ == "__main__":
    unittest.main()
