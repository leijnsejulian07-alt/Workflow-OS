import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.awin_transaction_http_transport import AwinTransactionFetchResult
from workflow_os.audit import AuditRevenueLedger
from workflow_os.awin_transaction_ingestion import (
    canonicalize_awin_api_transaction,
    ingest_awin_transaction_fetch,
)


class _KnownOpportunityLedger:
    def __init__(self, known=True):
        self.known = known

    def latest_decision(self, opportunity_id):
        if self.known and opportunity_id == "opp-aff-1":
            return {"opportunity_id": opportunity_id, "decision": "ACCEPT"}
        return None


def _row(**overrides):
    value = {
        "id": 259630312,
        "advertiserId": 7052,
        "publisherId": 189069,
        "commissionStatus": "approved",
        "commissionAmount": {"amount": 5.59, "currency": "EUR"},
        "clickRefs": {"clickRef": "workflow-os:opp-aff-1"},
        "transactionDate": "2026-08-27T22:04:00",
        "validationDate": "2026-08-28T08:15:00",
    }
    value.update(overrides)
    return value


def _fetch(*rows, **overrides):
    value = {
        "publisher_id": 189069,
        "start_at": "2026-08-27T00:00:00Z",
        "end_at": "2026-08-28T00:00:00Z",
        "date_type": "transaction",
        "status": None,
        "advertiser_id": None,
        "transactions": tuple(rows or (_row(),)),
        "evidence_sha256": "a" * 64,
    }
    value.update(overrides)
    return AwinTransactionFetchResult(**value)


class AwinTransactionIngestionTests(unittest.TestCase):
    def test_official_api_row_maps_to_existing_canonical_evidence_shape(self):
        opportunity_id, canonical = canonicalize_awin_api_transaction(_fetch(), _row())
        self.assertEqual(opportunity_id, "opp-aff-1")
        self.assertEqual(canonical["transaction_id"], "259630312")
        self.assertEqual(canonical["publisher_id"], 189069)
        self.assertEqual(canonical["advertiser_id"], 7052)
        self.assertEqual(canonical["status"], "approved")
        self.assertEqual(canonical["commission_eur"], 5.59)
        self.assertEqual(canonical["currency"], "EUR")
        self.assertEqual(canonical["click_ref"], "workflow-os:opp-aff-1")
        self.assertEqual(canonical["transaction_at"], "2026-08-27T22:04:00+00:00")
        self.assertEqual(canonical["validation_at"], "2026-08-28T08:15:00+00:00")
        self.assertEqual(canonical["evidence_sha256"], "a" * 64)

    def test_fetch_records_evidence_but_never_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            evidence = ingest_awin_transaction_fetch(
                _fetch(),
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].opportunity_id, "opp-aff-1")
            self.assertFalse(evidence[0].proves_received_cash)
            self.assertEqual(audit.gross_cash_eur(), 0.0)
            self.assertTrue(audit.verify_audit_chain())

    def test_exact_fetch_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            kwargs = dict(
                opportunity_ledger=_KnownOpportunityLedger(),
                audit_ledger=audit,
            )
            first = ingest_awin_transaction_fetch(_fetch(), **kwargs)
            second = ingest_awin_transaction_fetch(_fetch(), **kwargs)
            self.assertEqual(first, second)
            self.assertTrue(audit.verify_audit_chain())

    def test_unknown_clickref_opportunity_fails_closed_before_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            with self.assertRaisesRegex(ValueError, "unknown Workflow OS opportunity"):
                ingest_awin_transaction_fetch(
                    _fetch(),
                    opportunity_ledger=_KnownOpportunityLedger(known=False),
                    audit_ledger=audit,
                )
            self.assertEqual(audit.gross_cash_eur(), 0.0)

    def test_publisher_and_requested_advertiser_identity_must_match(self):
        with self.assertRaisesRegex(ValueError, "publisherId"):
            canonicalize_awin_api_transaction(_fetch(), _row(publisherId=999))
        with self.assertRaisesRegex(ValueError, "advertiserId"):
            canonicalize_awin_api_transaction(
                _fetch(advertiser_id=7052), _row(advertiserId=999)
            )

    def test_only_workflow_os_clickref_is_accepted(self):
        for click_refs in (
            {},
            {"clickRef": "other-system:opp-aff-1"},
            {"clickRef": "workflow-os:"},
            {"clickRef": 123},
        ):
            with self.subTest(click_refs=click_refs):
                with self.assertRaises(ValueError):
                    canonicalize_awin_api_transaction(
                        _fetch(), _row(clickRefs=click_refs)
                    )

    def test_pending_may_have_no_validation_date(self):
        opportunity_id, canonical = canonicalize_awin_api_transaction(
            _fetch(),
            _row(commissionStatus="pending", validationDate=None),
        )
        self.assertEqual(opportunity_id, "opp-aff-1")
        self.assertIsNone(canonical["validation_at"])

    def test_validated_status_requires_validation_date(self):
        for status in ("approved", "declined", "deleted"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "validationDate"):
                    canonicalize_awin_api_transaction(
                        _fetch(),
                        _row(commissionStatus=status, validationDate=None),
                    )

    def test_non_eur_or_malformed_commission_fails_closed(self):
        bad_values = (
            {"amount": 1, "currency": "USD"},
            {"currency": "EUR"},
            "5.00",
        )
        for commission in bad_values:
            with self.subTest(commission=commission):
                with self.assertRaises(ValueError):
                    canonicalize_awin_api_transaction(
                        _fetch(), _row(commissionAmount=commission)
                    )

    def test_duplicate_transaction_status_in_single_response_is_rejected(self):
        duplicate = _row()
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            with self.assertRaisesRegex(ValueError, "duplicate Awin transaction/status"):
                ingest_awin_transaction_fetch(
                    _fetch(duplicate, dict(duplicate)),
                    opportunity_ledger=_KnownOpportunityLedger(),
                    audit_ledger=audit,
                )


if __name__ == "__main__":
    unittest.main()
