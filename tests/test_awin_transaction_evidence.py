import tempfile
import unittest
from pathlib import Path

from workflow_os.audit import AuditRevenueLedger
from workflow_os.awin_transaction_evidence import (
    normalize_awin_transaction,
    record_awin_transaction_evidence,
)


class _KnownOpportunityLedger:
    def __init__(self, known=True):
        self.known = known

    def latest_decision(self, opportunity_id):
        if self.known and opportunity_id == "opp-aff-1":
            return {"opportunity_id": opportunity_id, "decision": "ACCEPT"}
        return None


def _raw(**overrides):
    value = {
        "transaction_id": "tx-123",
        "publisher_id": 12345,
        "advertiser_id": 67890,
        "status": "approved",
        "commission_eur": "12.34",
        "currency": "EUR",
        "transaction_at": "2026-08-27T10:00:00+00:00",
        "validation_at": "2026-08-28T01:00:00+00:00",
        "click_ref": "workflow-os:opp-aff-1",
        "evidence_sha256": "a" * 64,
    }
    value.update(overrides)
    return value


class AwinTransactionEvidenceTests(unittest.TestCase):
    def test_approved_commission_is_evidence_not_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            evidence = record_awin_transaction_evidence(
                _raw(),
                expected_opportunity_id="opp-aff-1",
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            self.assertEqual(evidence.status, "approved")
            self.assertEqual(evidence.commission_cents, 1234)
            self.assertFalse(evidence.proves_received_cash)
            self.assertEqual(audit.gross_cash_eur(), 0.0)
            self.assertTrue(audit.verify_audit_chain())

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            kwargs = dict(
                expected_opportunity_id="opp-aff-1",
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            first = record_awin_transaction_evidence(_raw(), **kwargs)
            second = record_awin_transaction_evidence(_raw(), **kwargs)
            self.assertEqual(first, second)
            self.assertTrue(audit.verify_audit_chain())

    def test_status_transition_creates_separate_immutable_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            kwargs = dict(
                expected_opportunity_id="opp-aff-1",
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            pending = _raw(
                status="pending",
                validation_at=None,
                evidence_sha256="b" * 64,
            )
            approved = _raw(status="approved", evidence_sha256="c" * 64)
            record_awin_transaction_evidence(pending, **kwargs)
            record_awin_transaction_evidence(approved, **kwargs)
            self.assertEqual(audit.gross_cash_eur(), 0.0)
            self.assertTrue(audit.verify_audit_chain())

    def test_replay_with_changed_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            kwargs = dict(
                expected_opportunity_id="opp-aff-1",
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            record_awin_transaction_evidence(_raw(), **kwargs)
            with self.assertRaisesRegex(ValueError, "already exists with different content"):
                record_awin_transaction_evidence(
                    _raw(commission_eur="99.99", evidence_sha256="b" * 64), **kwargs
                )

    def test_unknown_opportunity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            with self.assertRaisesRegex(ValueError, "unknown Workflow OS opportunity"):
                record_awin_transaction_evidence(
                    _raw(),
                    expected_opportunity_id="opp-aff-1",
                    opportunity_ledger=_KnownOpportunityLedger(known=False),
                    audit_ledger=audit,
                )
            self.assertEqual(audit.gross_cash_eur(), 0.0)

    def test_click_ref_must_bind_exact_opportunity(self):
        with self.assertRaisesRegex(ValueError, "click_ref"):
            normalize_awin_transaction(
                _raw(click_ref="workflow-os:opp-other"),
                expected_opportunity_id="opp-aff-1",
            )

    def test_non_eur_and_invalid_commission_fail_closed(self):
        for bad in (
            _raw(currency="USD"),
            _raw(commission_eur=-1),
            _raw(commission_eur=float("inf")),
            _raw(commission_eur="1.001"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    normalize_awin_transaction(bad, expected_opportunity_id="opp-aff-1")

    def test_validated_status_requires_validation_timestamp(self):
        for status in ("approved", "declined", "deleted"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "validation_at"):
                    normalize_awin_transaction(
                        _raw(status=status, validation_at=None),
                        expected_opportunity_id="opp-aff-1",
                    )

    def test_pending_may_lack_validation_timestamp_and_never_proves_cash(self):
        evidence = normalize_awin_transaction(
            _raw(status="pending", validation_at=None, commission_eur="0.00"),
            expected_opportunity_id="opp-aff-1",
        )
        self.assertEqual(evidence.status, "pending")
        self.assertEqual(evidence.commission_cents, 0)
        self.assertFalse(evidence.proves_received_cash)


if __name__ == "__main__":
    unittest.main()
