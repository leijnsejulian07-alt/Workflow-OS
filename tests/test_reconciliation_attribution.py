import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.audit import AuditRevenueLedger, CashReceipt
from workflow_os.ledger import OpportunityLedger
from workflow_os.reconciliation import RevenueReconciliationLedger
from workflow_os.reconciliation_attribution import promote_attributed_cash_receipt


class ReconciliationAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        OpportunityLedger(self.path)
        self.audit = AuditRevenueLedger(self.path)
        self.reconciliation = RevenueReconciliationLedger(self.path)
        self.evidence = "a" * 64

    def tearDown(self):
        self.tmp.cleanup()

    def _opportunity(self, opportunity_id="op-1", source_platform="test"):
        with managed_connection(sqlite3.connect(self.path)) as db:
            db.execute(
                """
                INSERT INTO opportunities(
                    opportunity_id, normalized_json, source_platform, campaign_id,
                    discovered_at, updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    opportunity_id,
                    "{}",
                    source_platform,
                    "campaign-1",
                    "2026-08-14T05:00:00+00:00",
                    "2026-08-14T05:00:00+00:00",
                ),
            )

    def _record_and_attribute(self):
        self._opportunity()
        self.audit.record_cash(
            CashReceipt(
                "r1",
                "test",
                125.50,
                "2026-08-14T06:00:00+00:00",
                "payout-1",
            )
        )
        self.audit.attribute_cash(
            "r1", "op-1", attributed_at="2026-08-14T06:01:00+00:00"
        )

    def test_promotes_only_proven_attributed_cash(self):
        self._record_and_attribute()
        event = promote_attributed_cash_receipt(
            legacy_db_path=self.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="r1",
            evidence_sha256=self.evidence,
        )
        self.assertEqual(event.opportunity_id, "op-1")
        self.assertEqual(event.platform, "test")
        self.assertEqual(event.amount_cents, 12550)
        summary = self.reconciliation.realized_summary("op-1")
        self.assertEqual(summary.realized_cash_eur, 125.50)
        self.assertEqual(summary.sample_count, 1)

    def test_replay_is_idempotent_when_evidence_matches(self):
        self._record_and_attribute()
        first = promote_attributed_cash_receipt(
            legacy_db_path=self.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="r1",
            evidence_sha256=self.evidence,
        )
        second = promote_attributed_cash_receipt(
            legacy_db_path=self.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="r1",
            evidence_sha256=self.evidence,
        )
        self.assertEqual(first, second)
        self.assertEqual(self.reconciliation.realized_summary("op-1").sample_count, 1)

    def test_unattributed_receipt_fails_closed(self):
        self._opportunity()
        self.audit.record_cash(
            CashReceipt(
                "r1", "test", 10, "2026-08-14T06:00:00+00:00", "payout-1"
            )
        )
        with self.assertRaises(ValueError):
            promote_attributed_cash_receipt(
                legacy_db_path=self.path,
                reconciliation_ledger=self.reconciliation,
                receipt_id="r1",
                evidence_sha256=self.evidence,
            )
        self.assertEqual(self.reconciliation.realized_summary("op-1").sample_count, 0)

    def test_platform_drift_after_attribution_fails_closed(self):
        self._record_and_attribute()
        with managed_connection(sqlite3.connect(self.path)) as db:
            db.execute(
                "UPDATE opportunities SET source_platform='other' WHERE opportunity_id='op-1'"
            )
        with self.assertRaises(ValueError):
            promote_attributed_cash_receipt(
                legacy_db_path=self.path,
                reconciliation_ledger=self.reconciliation,
                receipt_id="r1",
                evidence_sha256=self.evidence,
            )

    def test_evidence_conflict_on_same_receipt_fails_closed(self):
        self._record_and_attribute()
        promote_attributed_cash_receipt(
            legacy_db_path=self.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="r1",
            evidence_sha256=self.evidence,
        )
        with self.assertRaises(ValueError):
            promote_attributed_cash_receipt(
                legacy_db_path=self.path,
                reconciliation_ledger=self.reconciliation,
                receipt_id="r1",
                evidence_sha256="b" * 64,
            )

    def test_caller_cannot_supply_or_override_opportunity(self):
        self._record_and_attribute()
        event = promote_attributed_cash_receipt(
            legacy_db_path=self.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="r1",
            evidence_sha256=self.evidence,
        )
        self.assertEqual(event.opportunity_id, "op-1")

    def test_missing_attribution_database_fails_closed(self):
        with self.assertRaises(ValueError):
            promote_attributed_cash_receipt(
                legacy_db_path=Path(self.tmp.name) / "missing.sqlite3",
                reconciliation_ledger=self.reconciliation,
                receipt_id="r1",
                evidence_sha256=self.evidence,
            )


if __name__ == "__main__":
    unittest.main()
