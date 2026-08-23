from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.adapters.whop_webhook import VerifiedWhopWebhook
from workflow_os.whop_webhook_inbox import WhopWebhookInbox


class WhopWebhookInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow.sqlite3"
        self.inbox = WhopWebhookInbox(self.path)
        self.event = VerifiedWhopWebhook(
            webhook_id="msg_123",
            webhook_timestamp=1787468400,
            event_id="msg_123",
            event_type="payment.succeeded",
            api_version="v1",
            occurred_at="2026-08-23T07:00:00+00:00",
            account_id="biz_123",
            data={"id": "pay_123", "status": "paid"},
            payload_sha256=hashlib.sha256(b"signed payload").hexdigest(),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_record_and_pending_round_trip(self) -> None:
        recorded = self.inbox.record(
            self.event,
            received_at=datetime(2026, 8, 23, 7, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(recorded.status, "PENDING")
        pending = self.inbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].webhook_id, "msg_123")
        self.assertEqual(pending[0].data["id"], "pay_123")

    def test_exact_delivery_replay_is_idempotent(self) -> None:
        first = self.inbox.record(self.event)
        second = self.inbox.record(self.event)
        self.assertEqual(first.webhook_id, second.webhook_id)
        self.assertEqual(len(self.inbox.pending()), 1)

    def test_same_webhook_id_with_changed_verified_content_fails_closed(self) -> None:
        self.inbox.record(self.event)
        drifted = VerifiedWhopWebhook(
            webhook_id=self.event.webhook_id,
            webhook_timestamp=self.event.webhook_timestamp,
            event_id=self.event.event_id,
            event_type=self.event.event_type,
            api_version=self.event.api_version,
            occurred_at=self.event.occurred_at,
            account_id=self.event.account_id,
            data={"id": "pay_other", "status": "paid"},
            payload_sha256=hashlib.sha256(b"different signed payload").hexdigest(),
        )
        with self.assertRaisesRegex(ValueError, "different verified content"):
            self.inbox.record(drifted)

    def test_processed_event_is_not_returned_pending(self) -> None:
        self.inbox.record(self.event)
        self.inbox.mark_processed(
            self.event.webhook_id,
            expected_payload_sha256=self.event.payload_sha256,
            processed_at=datetime(2026, 8, 23, 7, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(self.inbox.pending(), [])
        replay = self.inbox.record(self.event)
        self.assertEqual(replay.status, "PROCESSED")
        self.assertEqual(self.inbox.pending(), [])

    def test_acknowledgement_requires_exact_payload_digest(self) -> None:
        self.inbox.record(self.event)
        with self.assertRaisesRegex(ValueError, "digest drifted"):
            self.inbox.mark_processed(
                self.event.webhook_id,
                expected_payload_sha256="0" * 64,
            )
        self.assertEqual(len(self.inbox.pending()), 1)

    def test_unknown_event_cannot_be_acknowledged(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.inbox.mark_processed(
                "msg_missing",
                expected_payload_sha256="0" * 64,
            )

    def test_pending_limit_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 200"):
            self.inbox.pending(limit=0)
        with self.assertRaisesRegex(ValueError, "between 1 and 200"):
            self.inbox.pending(limit=201)
        with self.assertRaisesRegex(ValueError, "between 1 and 200"):
            self.inbox.pending(limit=True)

    def test_naive_receipt_and_processed_times_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.inbox.record(self.event, received_at=datetime(2026, 8, 23, 7, 1))
        self.inbox.record(self.event)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.inbox.mark_processed(
                self.event.webhook_id,
                expected_payload_sha256=self.event.payload_sha256,
                processed_at=datetime(2026, 8, 23, 7, 2),
            )


if __name__ == "__main__":
    unittest.main()
