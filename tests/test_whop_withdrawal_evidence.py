from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.whop_webhook_inbox import WhopInboxEvent
from workflow_os.whop_withdrawal_evidence import (
    WhopWithdrawalEvidenceLedger,
    normalize_whop_withdrawal_event,
)


DIGEST = "a" * 64


def event(**overrides: object) -> WhopInboxEvent:
    data: dict[str, object] = {
        "id": "wdrl_123",
        "amount": 12.5,
        "currency": "usd",
        "status": "completed",
        "trace_code": "trace_123",
        "ledger_account": {"company_id": "biz_123"},
    }
    supplied_data = overrides.pop("data", None)
    if supplied_data is not None:
        data = dict(supplied_data)  # type: ignore[arg-type]
    values: dict[str, object] = {
        "webhook_id": "msg_123",
        "event_type": "withdrawal.updated",
        "occurred_at": "2026-08-23T10:00:00+00:00",
        "account_id": "biz_123",
        "payload_sha256": DIGEST,
        "data": data,
        "status": "PENDING",
    }
    values.update(overrides)
    return WhopInboxEvent(**values)  # type: ignore[arg-type]


class WhopWithdrawalEvidenceTests(unittest.TestCase):
    def test_normalizes_withdrawal_without_asserting_received_cash(self) -> None:
        evidence = normalize_whop_withdrawal_event(event())
        self.assertEqual(evidence.withdrawal_id, "wdrl_123")
        self.assertEqual(evidence.amount, "12.5")
        self.assertEqual(evidence.currency, "USD")
        self.assertEqual(evidence.status, "completed")
        self.assertFalse(evidence.proves_received_cash)

    def test_rejects_non_withdrawal_event(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a supported"):
            normalize_whop_withdrawal_event(event(event_type="payment.succeeded"))

    def test_rejects_company_identity_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "company identity"):
            normalize_whop_withdrawal_event(
                event(
                    data={
                        "id": "wdrl_123",
                        "amount": 12.5,
                        "ledger_account": {"company_id": "biz_other"},
                    }
                )
            )

    def test_rejects_invalid_amount_and_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount"):
            normalize_whop_withdrawal_event(
                event(data={"id": "wdrl_123", "amount": True})
            )
        with self.assertRaisesRegex(ValueError, "digest"):
            normalize_whop_withdrawal_event(event(payload_sha256="BAD"))

    def test_records_multiple_status_events_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WhopWithdrawalEvidenceLedger(Path(tmp) / "withdrawals.sqlite3")
            first = normalize_whop_withdrawal_event(
                event(
                    webhook_id="msg_1",
                    event_type="withdrawal.created",
                    occurred_at="2026-08-23T09:00:00+00:00",
                    data={"id": "wdrl_123", "amount": 12.5, "status": "requested"},
                )
            )
            second = normalize_whop_withdrawal_event(
                event(webhook_id="msg_2", occurred_at="2026-08-23T10:00:00+00:00")
            )
            ledger.record(second)
            ledger.record(first)
            rows = ledger.events_for_withdrawal("wdrl_123")
            self.assertEqual([row.webhook_id for row in rows], ["msg_1", "msg_2"])
            self.assertTrue(all(not row.proves_received_cash for row in rows))

    def test_exact_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WhopWithdrawalEvidenceLedger(Path(tmp) / "withdrawals.sqlite3")
            evidence = normalize_whop_withdrawal_event(event())
            ledger.record(evidence)
            ledger.record(evidence)
            self.assertEqual(len(ledger.events_for_withdrawal("wdrl_123")), 1)

    def test_webhook_id_content_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WhopWithdrawalEvidenceLedger(Path(tmp) / "withdrawals.sqlite3")
            original = normalize_whop_withdrawal_event(event())
            changed = normalize_whop_withdrawal_event(
                event(data={"id": "wdrl_123", "amount": 99, "status": "completed"})
            )
            ledger.record(original)
            with self.assertRaisesRegex(ValueError, "different withdrawal evidence"):
                ledger.record(changed)

    def test_webhook_sample_without_status_or_currency_is_preserved_as_unknown(self) -> None:
        evidence = normalize_whop_withdrawal_event(
            event(
                event_type="withdrawal.updated",
                data={
                    "id": "wdrl_123",
                    "amount": 6.9,
                    "fee_amount": 0.5,
                    "ledger_account": {"company_id": "biz_123"},
                    "estimated_availability": "2026-08-24T10:00:00+00:00",
                },
            )
        )
        self.assertIsNone(evidence.status)
        self.assertIsNone(evidence.currency)
        self.assertFalse(evidence.proves_received_cash)


if __name__ == "__main__":
    unittest.main()
