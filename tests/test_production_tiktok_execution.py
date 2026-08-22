import tempfile
import unittest
from unittest.mock import patch

from workflow_os.adapters.tiktok_direct_post import (
    TikTokCreatorSnapshot,
    TikTokDirectPostOptions,
)
from workflow_os.credentials import CredentialRef
from workflow_os.production_reservation_pipeline import PreparedProductionSubmission
from workflow_os.production_tiktok_execution import execute_reserved_tiktok_production_submission
from workflow_os.side_effects import SideEffectLedger
from workflow_os.submission_execution import SubmissionAttemptResult, reserve_submission
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


DIGEST = "a" * 64


def request(destination_url="https://www.tiktok.com/upload"):
    return SubmissionRequest(
        opportunity_id="opp-1",
        source_platform="cliparmy",
        campaign_url="https://cliparmy.com/campaigns/example",
        destination_url=destination_url,
        caption="Campaign-compliant caption",
        asset=SubmissionAsset(
            path="outputs/opp-1/final.mp4",
            media_type="video/mp4",
            size_bytes=1024,
            sha256=DIGEST,
        ),
        rights_verified=True,
        account_authorized=True,
        disclosure_satisfied=True,
        campaign_requirements_verified=True,
    )


def options():
    return TikTokDirectPostOptions(
        privacy_level="SELF_ONLY",
        creator_snapshot=TikTokCreatorSnapshot(
            privacy_level_options=("SELF_ONLY",),
            verified=True,
        ),
        explicit_user_consent=True,
        client_audited=False,
    )


class ReservedTikTokProductionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(f"{self.tempdir.name}/side-effects.sqlite3")
        self.request = request()
        reservation = reserve_submission(
            self.request,
            allowed_destination_hosts={"www.tiktok.com"},
            ledger=self.ledger,
        )
        self.prepared = PreparedProductionSubmission(
            verified=None,
            request=self.request,
            reservation=reservation,
        )
        self.kwargs = {
            "ledger": self.ledger,
            "options": options(),
            "credential_ref": CredentialRef("tiktok", "acct-1", "access_token"),
            "credential_provider": object(),
            "asset_root": self.tempdir.name,
            "transport": object(),
            "sleep": lambda _: None,
        }

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("workflow_os.production_tiktok_execution.execute_tiktok_direct_post_with_credential")
    def test_confirmed_tiktok_post_marks_reserved_side_effect_succeeded(self, execute_mock):
        execute_mock.return_value = SubmissionAttemptResult(
            outcome="APPLIED",
            external_reference="tiktok:post-123",
        )

        result = execute_reserved_tiktok_production_submission(
            self.prepared,
            **self.kwargs,
        )

        self.assertEqual(result.state, "SUCCEEDED")
        self.assertEqual(result.external_reference, "tiktok:post-123")
        self.assertEqual(result.attempt_count, 1)
        execute_mock.assert_called_once()

    @patch("workflow_os.production_tiktok_execution.execute_tiktok_direct_post_with_credential")
    def test_proven_not_applied_is_retryable(self, execute_mock):
        execute_mock.return_value = SubmissionAttemptResult(outcome="NOT_APPLIED")

        result = execute_reserved_tiktok_production_submission(
            self.prepared,
            **self.kwargs,
        )

        self.assertEqual(result.state, "FAILED_RETRYABLE")
        self.assertEqual(result.attempt_count, 1)

    @patch("workflow_os.production_tiktok_execution.execute_tiktok_direct_post_with_credential")
    def test_ambiguous_adapter_exception_becomes_unknown(self, execute_mock):
        execute_mock.side_effect = TimeoutError("connection lost after dispatch")

        with self.assertRaises(TimeoutError):
            execute_reserved_tiktok_production_submission(
                self.prepared,
                **self.kwargs,
            )

        current = self.ledger.get(self.prepared.reservation.side_effect.idempotency_key)
        self.assertEqual(current.state, "UNKNOWN")
        self.assertEqual(current.attempt_count, 1)

    @patch("workflow_os.production_tiktok_execution.execute_tiktok_direct_post_with_credential")
    def test_non_tiktok_destination_fails_before_execution(self, execute_mock):
        evil_request = request("https://evil.example/upload")
        reservation = reserve_submission(
            evil_request,
            allowed_destination_hosts={"evil.example"},
            ledger=self.ledger,
        )
        prepared = PreparedProductionSubmission(
            verified=None,
            request=evil_request,
            reservation=reservation,
        )

        with self.assertRaisesRegex(ValueError, "approved TikTok origin"):
            execute_reserved_tiktok_production_submission(
                prepared,
                **self.kwargs,
            )

        self.assertEqual(reservation.side_effect.state, "RESERVED")
        execute_mock.assert_not_called()

    @patch("workflow_os.production_tiktok_execution.execute_tiktok_direct_post_with_credential")
    def test_foreign_ledger_fails_before_execution(self, execute_mock):
        foreign = SideEffectLedger(f"{self.tempdir.name}/foreign.sqlite3")

        with self.assertRaisesRegex(RuntimeError, "missing from the supplied ledger"):
            execute_reserved_tiktok_production_submission(
                self.prepared,
                **{**self.kwargs, "ledger": foreign},
            )

        execute_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
