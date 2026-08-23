from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.audit import AuditRevenueLedger, CashReceipt
from workflow_os.durable_side_effect_binding import DurableSideEffectBinding
from workflow_os.publication_payout_attribution import (
    PublicationPayoutEvidence,
    attribute_cash_from_publication_evidence,
)
from workflow_os.publication_provenance import PublicationProvenanceLedger
from workflow_os.side_effects import SideEffectLedger


class PublicationPayoutAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.provenance = PublicationProvenanceLedger(root / "provenance.sqlite")

        with sqlite3.connect(self.audit.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS opportunities ("
                "opportunity_id TEXT PRIMARY KEY, source_platform TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO opportunities(opportunity_id, source_platform) VALUES(?,?)",
                ("opp-1", "cliparmy"),
            )
            db.execute(
                "INSERT INTO opportunities(opportunity_id, source_platform) VALUES(?,?)",
                ("opp-2", "cliparmy"),
            )

        self.audit.record_cash(
            CashReceipt(
                receipt_id="receipt-1",
                source_platform="cliparmy",
                amount_eur=25.0,
                received_at="2026-08-23T01:00:00+00:00",
                external_reference="payout-1",
            )
        )
        self._record_publication("opp-1", "publish-1", "post-1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _record_publication(self, opportunity_id: str, key: str, reference: str) -> None:
        reserved = self.effects.reserve(
            idempotency_key=key,
            action="publish_submission",
            target="https://www.tiktok.com/",
            payload={"opportunity_id": opportunity_id},
            max_attempts=3,
        )
        binding = DurableSideEffectBinding(
            job_id=1 if key == "publish-1" else 2,
            job_request_fingerprint=("a" if key == "publish-1" else "b") * 64,
            opportunity_id=opportunity_id,
            side_effect_idempotency_key=reserved.idempotency_key,
            side_effect_request_fingerprint=reserved.request_fingerprint,
        )
        self.effects.begin_attempt(key)
        self.effects.mark_succeeded(key, external_reference=reference)
        self.provenance.record_confirmed_publication(
            binding,
            side_effect_ledger=self.effects,
        )

    def _evidence(self, **changes: str) -> PublicationPayoutEvidence:
        values = {
            "payout_event_id": "payout-1",
            "receipt_id": "receipt-1",
            "publication_target": "https://www.tiktok.com/",
            "publication_reference": "post-1",
            "evidence_sha256": "c" * 64,
        }
        values.update(changes)
        return PublicationPayoutEvidence(**values)

    def test_cash_is_attributed_through_publication_provenance(self):
        provenance = attribute_cash_from_publication_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self.assertEqual("opp-1", provenance.opportunity_id)
        self.assertEqual(25.0, self.audit.realized_cash_eur("opp-1"))
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-2"))
        self.assertTrue(self.audit.verify_audit_chain())

    def test_exact_replay_is_idempotent(self):
        first = attribute_cash_from_publication_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        second = attribute_cash_from_publication_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self.assertEqual(first, second)
        self.assertEqual(25.0, self.audit.realized_cash_eur("opp-1"))

    def test_unknown_publication_is_rejected_before_attribution(self):
        with self.assertRaisesRegex(ValueError, "not proven provenance"):
            attribute_cash_from_publication_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(publication_reference="unknown-post"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-1"))

    def test_receipt_reference_must_match_payout_event(self):
        with self.assertRaisesRegex(ValueError, "does not match payout event"):
            attribute_cash_from_publication_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(payout_event_id="different-payout"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-1"))

    def test_unknown_receipt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cash receipt does not exist"):
            attribute_cash_from_publication_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(receipt_id="missing"),
            )

    def test_malformed_evidence_digest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            attribute_cash_from_publication_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(evidence_sha256="BAD"),
            )

    def test_provider_event_cannot_be_rebound_to_another_publication(self):
        attribute_cash_from_publication_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self._record_publication("opp-2", "publish-2", "post-2")
        with self.assertRaisesRegex(ValueError, "event_id already exists with different content"):
            attribute_cash_from_publication_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(publication_reference="post-2"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-2"))


if __name__ == "__main__":
    unittest.main()
