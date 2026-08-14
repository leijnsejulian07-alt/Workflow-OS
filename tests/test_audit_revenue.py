import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.audit import AuditRevenueLedger, CashReceipt


class AuditRevenueLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        self.ledger = AuditRevenueLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_audit_event_is_idempotent_and_chain_verifies(self):
        args = dict(event_id="evt-1", event_type="opportunity.accepted", payload={"decision": "ACCEPT"}, subject_id="op-1", occurred_at="2026-08-14T06:00:00+00:00")
        first = self.ledger.append_event(**args)
        second = self.ledger.append_event(**args)
        self.assertEqual(first, second)
        self.assertTrue(self.ledger.verify_audit_chain())

    def test_event_id_cannot_be_reused_with_different_content(self):
        self.ledger.append_event("evt-1", "a", {"x": 1}, occurred_at="2026-08-14T06:00:00+00:00")
        with self.assertRaises(ValueError):
            self.ledger.append_event("evt-1", "a", {"x": 2}, occurred_at="2026-08-14T06:00:00+00:00")

    def test_tampered_audit_row_is_detected(self):
        self.ledger.append_event("evt-1", "a", {"x": 1}, occurred_at="2026-08-14T06:00:00+00:00")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE audit_events SET event_json='{}' WHERE event_id='evt-1'")
        self.assertFalse(self.ledger.verify_audit_chain())

    def test_cash_requires_positive_bounded_reconciled_receipt(self):
        with self.assertRaises(ValueError):
            self.ledger.record_cash(CashReceipt("r0", "test", 0, "2026-08-14T06:00:00+00:00", "payout-0"))
        self.assertEqual(self.ledger.gross_cash_eur(), 0)

    def test_cash_receipt_is_idempotent_not_double_counted(self):
        receipt = CashReceipt("r1", "test", 125.50, "2026-08-14T06:00:00+00:00", "payout-1")
        self.ledger.record_cash(receipt)
        self.ledger.record_cash(receipt)
        self.assertEqual(self.ledger.gross_cash_eur(), 125.50)

    def test_receipt_identity_cannot_change_amount(self):
        self.ledger.record_cash(CashReceipt("r1", "test", 100, "2026-08-14T06:00:00+00:00", "payout-1"))
        with self.assertRaises(ValueError):
            self.ledger.record_cash(CashReceipt("r1", "test", 200, "2026-08-14T06:00:00+00:00", "payout-1"))

    def test_external_reference_cannot_be_counted_twice(self):
        self.ledger.record_cash(CashReceipt("r1", "test", 100, "2026-08-14T06:00:00+00:00", "payout-1"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.record_cash(CashReceipt("r2", "test", 100, "2026-08-14T06:00:00+00:00", "payout-1"))

    def test_payload_size_is_bounded(self):
        with self.assertRaises(ValueError):
            self.ledger.append_event("evt-big", "input", {"body": "x" * (65 * 1024)}, occurred_at="2026-08-14T06:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
