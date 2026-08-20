import tempfile
import unittest
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger
from workflow_os.submission_execution import reserve_submission
from workflow_os.submissions import SubmissionAsset, SubmissionRequest


DIGEST = "a" * 64


class SubmissionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "side-effects.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def valid_request(self, **changes):
        values = {
            "opportunity_id": "opp-123",
            "source_platform": "whop",
            "campaign_url": "https://whop.com/content-rewards/campaign-123",
            "destination_url": "https://www.tiktok.com/upload",
            "caption": "Campaign clip",
            "asset": SubmissionAsset("renders/clip.mp4", "video/mp4", 1024, DIGEST),
            "rights_verified": True,
            "account_authorized": True,
            "disclosure_satisfied": True,
            "campaign_requirements_verified": True,
        }
        values.update(changes)
        return SubmissionRequest(**values)

    def reserve(self, request, *, max_attempts=3):
        return reserve_submission(
            request,
            allowed_destination_hosts={"www.tiktok.com", "www.instagram.com"},
            ledger=self.ledger,
            max_attempts=max_attempts,
        )

    def test_verified_submission_is_reserved_before_execution(self):
        result = self.reserve(self.valid_request())
        self.assertTrue(result.decision.allowed)
        self.assertIsNotNone(result.side_effect)
        self.assertEqual(result.side_effect.state, "RESERVED")
        self.assertEqual(result.side_effect.action, "publish_submission")
        self.assertEqual(result.side_effect.target, "https://www.tiktok.com/upload")
        self.assertEqual(result.side_effect.attempt_count, 0)

    def test_same_submission_reservation_is_idempotent(self):
        first = self.reserve(self.valid_request())
        second = self.reserve(self.valid_request())
        self.assertEqual(first.side_effect, second.side_effect)
        self.assertEqual(first.decision.idempotency_key, second.decision.idempotency_key)

    def test_denied_submission_never_creates_side_effect(self):
        result = self.reserve(self.valid_request(rights_verified=False))
        self.assertFalse(result.decision.allowed)
        self.assertIsNone(result.side_effect)
        self.assertIsNone(result.decision.idempotency_key)

    def test_changed_payload_gets_distinct_reservation(self):
        first = self.reserve(self.valid_request())
        second = self.reserve(self.valid_request(caption="Different approved caption"))
        self.assertNotEqual(first.decision.idempotency_key, second.decision.idempotency_key)
        self.assertNotEqual(first.side_effect.idempotency_key, second.side_effect.idempotency_key)

    def test_retry_budget_is_bounded_by_ledger(self):
        result = self.reserve(self.valid_request(), max_attempts=2)
        self.assertEqual(result.side_effect.max_attempts, 2)
        self.ledger.begin_attempt(result.side_effect.idempotency_key)
        self.ledger.mark_failed(result.side_effect.idempotency_key, definitely_not_applied=True)
        self.ledger.begin_attempt(result.side_effect.idempotency_key)
        self.ledger.mark_failed(result.side_effect.idempotency_key, definitely_not_applied=True)
        with self.assertRaises(RuntimeError):
            self.ledger.begin_attempt(result.side_effect.idempotency_key)

    def test_ambiguous_failure_blocks_blind_retry(self):
        result = self.reserve(self.valid_request())
        key = result.side_effect.idempotency_key
        self.ledger.begin_attempt(key)
        unknown = self.ledger.mark_failed(key, definitely_not_applied=False)
        self.assertEqual(unknown.state, "UNKNOWN")
        with self.assertRaises(RuntimeError):
            self.ledger.begin_attempt(key)


if __name__ == "__main__":
    unittest.main()
