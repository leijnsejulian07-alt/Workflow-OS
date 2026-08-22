import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.reconciliation import RevenueReconciliationLedger


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


class RevenueReconciliationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.ledger = RevenueReconciliationLedger(Path(self.tempdir.name) / "revenue.sqlite3")

    def record_cash(self, **overrides):
        values = {
            "platform": "tiktok",
            "external_event_id": "payout-1",
            "opportunity_id": "op-1",
            "event_type": "CASH_RECEIVED",
            "amount_eur": "42.50",
            "occurred_at": "2026-08-22T04:00:00+00:00",
            "evidence_sha256": DIGEST_A,
        }
        values.update(overrides)
        return self.ledger.record_event(**values)

    def test_received_cash_and_cost_feed_realized_learning(self):
        self.record_cash()
        self.ledger.record_event(
            platform="render",
            external_event_id="cost-1",
            opportunity_id="op-1",
            event_type="COST_INCURRED",
            amount_eur="7.50",
            occurred_at="2026-08-22T04:01:00+00:00",
            evidence_sha256=DIGEST_B,
        )

        summary = self.ledger.realized_summary("op-1")
        self.assertEqual(summary.realized_cash_eur, 42.5)
        self.assertEqual(summary.reconciled_cost_eur, 7.5)
        self.assertEqual(summary.realized_profit_eur, 35.0)
        self.assertEqual(summary.sample_count, 1)
        self.assertEqual(self.ledger.learning_decision("op-1").action, "KEEP")

    def test_exact_provider_replay_is_idempotent(self):
        first = self.record_cash()
        second = self.record_cash()
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.realized_summary("op-1").sample_count, 1)

    def test_conflicting_duplicate_external_id_fails_closed(self):
        self.record_cash()
        with self.assertRaises(ValueError):
            self.record_cash(amount_eur="99.00")

    def test_non_eur_and_unverifiable_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            self.record_cash(currency="USD")
        with self.assertRaises(ValueError):
            self.record_cash(evidence_sha256="not-a-digest")
        with self.assertRaises(ValueError):
            self.record_cash(evidence_sha256="A" * 64)

    def test_amount_is_exact_bounded_money_not_float_noise(self):
        for value in (True, 0, -1, float("inf"), float("nan"), "1.001"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.record_cash(external_event_id=f"bad-{value!s}", amount_eur=value)

    def test_timestamp_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            self.record_cash(occurred_at="2026-08-22T04:00:00")

    def test_full_reversal_neutralizes_cash_and_sample(self):
        self.record_cash()
        self.ledger.record_event(
            platform="tiktok",
            external_event_id="reversal-1",
            opportunity_id="op-1",
            event_type="CASH_REVERSED",
            amount_eur="42.50",
            occurred_at="2026-08-22T05:00:00+00:00",
            evidence_sha256=DIGEST_C,
            reference_external_event_id="payout-1",
        )
        summary = self.ledger.realized_summary("op-1")
        self.assertEqual(summary.realized_cash_eur, 0.0)
        self.assertEqual(summary.sample_count, 0)
        self.assertEqual(self.ledger.learning_decision("op-1").action, "PAUSE")

    def test_reversal_requires_exact_existing_matching_event(self):
        with self.assertRaises(ValueError):
            self.ledger.record_event(
                platform="tiktok",
                external_event_id="reversal-missing",
                opportunity_id="op-1",
                event_type="CASH_REVERSED",
                amount_eur="42.50",
                occurred_at="2026-08-22T05:00:00+00:00",
                evidence_sha256=DIGEST_C,
                reference_external_event_id="missing",
            )

        self.record_cash()
        with self.assertRaises(ValueError):
            self.ledger.record_event(
                platform="tiktok",
                external_event_id="reversal-wrong-amount",
                opportunity_id="op-1",
                event_type="CASH_REVERSED",
                amount_eur="1.00",
                occurred_at="2026-08-22T05:00:00+00:00",
                evidence_sha256=DIGEST_C,
                reference_external_event_id="payout-1",
            )
        with self.assertRaises(ValueError):
            self.ledger.record_event(
                platform="tiktok",
                external_event_id="reversal-wrong-opportunity",
                opportunity_id="op-2",
                event_type="CASH_REVERSED",
                amount_eur="42.50",
                occurred_at="2026-08-22T05:00:00+00:00",
                evidence_sha256=DIGEST_C,
                reference_external_event_id="payout-1",
            )

    def test_one_original_event_cannot_be_reversed_twice(self):
        self.record_cash()
        self.ledger.record_event(
            platform="tiktok",
            external_event_id="reversal-1",
            opportunity_id="op-1",
            event_type="CASH_REVERSED",
            amount_eur="42.50",
            occurred_at="2026-08-22T05:00:00+00:00",
            evidence_sha256=DIGEST_C,
            reference_external_event_id="payout-1",
        )
        with self.assertRaises(ValueError):
            self.ledger.record_event(
                platform="tiktok",
                external_event_id="reversal-2",
                opportunity_id="op-1",
                event_type="CASH_REVERSED",
                amount_eur="42.50",
                occurred_at="2026-08-22T05:05:00+00:00",
                evidence_sha256=DIGEST_D,
                reference_external_event_id="payout-1",
            )

    def test_cost_reversal_restores_realized_profit(self):
        self.record_cash(amount_eur="50.00")
        self.ledger.record_event(
            platform="render",
            external_event_id="cost-1",
            opportunity_id="op-1",
            event_type="COST_INCURRED",
            amount_eur="10.00",
            occurred_at="2026-08-22T04:01:00+00:00",
            evidence_sha256=DIGEST_B,
        )
        self.ledger.record_event(
            platform="render",
            external_event_id="cost-refund-1",
            opportunity_id="op-1",
            event_type="COST_REVERSED",
            amount_eur="10.00",
            occurred_at="2026-08-22T04:02:00+00:00",
            evidence_sha256=DIGEST_C,
            reference_external_event_id="cost-1",
        )
        summary = self.ledger.realized_summary("op-1")
        self.assertEqual(summary.reconciled_cost_eur, 0.0)
        self.assertEqual(summary.realized_profit_eur, 50.0)

    def test_no_events_fail_closed_to_pause(self):
        summary = self.ledger.realized_summary("op-empty")
        self.assertEqual(summary.realized_cash_eur, 0.0)
        self.assertEqual(summary.sample_count, 0)
        self.assertEqual(self.ledger.learning_decision("op-empty").action, "PAUSE")


if __name__ == "__main__":
    unittest.main()
