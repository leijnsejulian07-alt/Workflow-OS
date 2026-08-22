import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.ledger import OpportunityLedger
from workflow_os.reconciliation import RevenueReconciliationLedger
from workflow_os.resource_cost import ResourceCostLedger, promote_verified_cost


class ResourceCostLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        OpportunityLedger(self.path)
        self.costs = ResourceCostLedger(self.path)
        self.reconciliation = RevenueReconciliationLedger(self.path)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT INTO opportunities(
                    opportunity_id, normalized_json, source_platform, campaign_id,
                    discovered_at, updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    "op-1",
                    "{}",
                    "test",
                    "campaign-1",
                    "2026-08-22T07:00:00+00:00",
                    "2026-08-22T07:00:00+00:00",
                ),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, **overrides):
        values = {
            "cost_id": "cost-1",
            "opportunity_id": "op-1",
            "platform": "test",
            "amount_eur": "3.25",
            "occurred_at": "2026-08-22T07:05:00+00:00",
            "evidence_sha256": "a" * 64,
            "external_reference": "provider-charge-1",
        }
        values.update(overrides)
        return self.costs.record_cost(**values)

    def test_records_and_promotes_verified_cost(self):
        cost = self._record()
        self.assertEqual(cost.amount_cents, 325)
        event = promote_verified_cost(
            cost_ledger=self.costs,
            reconciliation_ledger=self.reconciliation,
            cost_id="cost-1",
        )
        self.assertEqual(event.opportunity_id, "op-1")
        self.assertEqual(event.event_type, "COST_INCURRED")
        self.assertEqual(
            self.reconciliation.realized_summary("op-1").reconciled_cost_eur,
            3.25,
        )

    def test_replay_is_idempotent(self):
        first = self._record()
        second = self._record()
        self.assertEqual(first, second)
        promote_verified_cost(
            cost_ledger=self.costs,
            reconciliation_ledger=self.reconciliation,
            cost_id="cost-1",
        )
        promote_verified_cost(
            cost_ledger=self.costs,
            reconciliation_ledger=self.reconciliation,
            cost_id="cost-1",
        )
        self.assertEqual(
            self.reconciliation.realized_summary("op-1").reconciled_cost_eur,
            3.25,
        )

    def test_unknown_opportunity_fails_closed(self):
        with self.assertRaises(ValueError):
            self._record(opportunity_id="missing")

    def test_platform_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            self._record(platform="other")

    def test_platform_drift_before_promotion_fails_closed(self):
        self._record()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE opportunities SET source_platform='other' WHERE opportunity_id='op-1'"
            )
        with self.assertRaises(ValueError):
            promote_verified_cost(
                cost_ledger=self.costs,
                reconciliation_ledger=self.reconciliation,
                cost_id="cost-1",
            )
        self.assertEqual(
            self.reconciliation.realized_summary("op-1").reconciled_cost_eur,
            0,
        )

    def test_conflicting_cost_id_fails_closed(self):
        self._record()
        with self.assertRaises(ValueError):
            self._record(amount_eur="4.00")

    def test_external_reference_cannot_be_reused(self):
        self._record()
        with self.assertRaises(ValueError):
            self._record(cost_id="cost-2")

    def test_invalid_money_and_evidence_fail_closed(self):
        for index, amount in enumerate((True, "0", "-1", "1.001", float("inf"))):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self._record(
                        cost_id=f"bad-{index}",
                        external_reference=f"bad-ref-{index}",
                        amount_eur=amount,
                    )
        with self.assertRaises(ValueError):
            self._record(
                cost_id="bad-digest",
                external_reference="bad-digest",
                evidence_sha256="ABC",
            )

    def test_caller_cannot_override_opportunity_on_promotion(self):
        self._record()
        event = promote_verified_cost(
            cost_ledger=self.costs,
            reconciliation_ledger=self.reconciliation,
            cost_id="cost-1",
        )
        self.assertEqual(event.opportunity_id, "op-1")


if __name__ == "__main__":
    unittest.main()
