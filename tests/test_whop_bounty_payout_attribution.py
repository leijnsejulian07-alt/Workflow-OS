from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.adapters.whop_bounty_submission import WHOP_BOUNTY_SUBMISSION_URL
from workflow_os.audit import AuditRevenueLedger, CashReceipt
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBinding
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_payout_attribution import (
    WhopBountyPayoutEvidence,
    attribute_cash_from_whop_bounty_evidence,
)
from workflow_os.whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenanceLedger,
)


class WhopBountyPayoutAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")

        with managed_connection(sqlite3.connect(self.audit.path)) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS opportunities ("
                "opportunity_id TEXT PRIMARY KEY, source_platform TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO opportunities(opportunity_id, source_platform) VALUES(?,?)",
                ("opp-whop-1", "whop_bounties"),
            )
            db.execute(
                "INSERT INTO opportunities(opportunity_id, source_platform) VALUES(?,?)",
                ("opp-whop-2", "whop_bounties"),
            )

        self.audit.record_cash(
            CashReceipt(
                receipt_id="receipt-whop-1",
                source_platform="whop_bounties",
                amount_eur=40.0,
                received_at="2026-08-24T12:00:00+00:00",
                external_reference="payout-whop-1",
            )
        )
        self._record_submission(
            opportunity_id="opp-whop-1",
            key="whop-bounty:job-1",
            reference="btys_submission123",
            job_id=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _record_submission(
        self,
        *,
        opportunity_id: str,
        key: str,
        reference: str,
        job_id: int,
    ) -> None:
        side_effect = self.effects.reserve(
            idempotency_key=key,
            action="submit_whop_bounty",
            target=WHOP_BOUNTY_SUBMISSION_URL,
            payload={"bounty_id": "bnty_example123", "job_id": job_id},
            max_attempts=3,
        )
        binding = DurableWhopBountyBinding(
            job_id=job_id,
            job_request_fingerprint=(str(job_id) * 64)[:64],
            opportunity_id=opportunity_id,
            bounty_id="bnty_example123",
            side_effect_idempotency_key=side_effect.idempotency_key,
            side_effect_request_fingerprint=side_effect.request_fingerprint,
        )
        self.effects.begin_attempt(side_effect.idempotency_key)
        self.effects.mark_succeeded(
            side_effect.idempotency_key,
            external_reference=reference,
        )
        self.provenance.record_confirmed_submission(
            binding,
            side_effect_ledger=self.effects,
        )

    def _evidence(self, **changes: str) -> WhopBountyPayoutEvidence:
        values = {
            "payout_event_id": "payout-whop-1",
            "receipt_id": "receipt-whop-1",
            "submission_reference": "btys_submission123",
            "evidence_sha256": "d" * 64,
        }
        values.update(changes)
        return WhopBountyPayoutEvidence(**values)

    def test_attributes_received_cash_through_confirmed_whop_submission(self):
        provenance = attribute_cash_from_whop_bounty_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self.assertEqual("opp-whop-1", provenance.opportunity_id)
        self.assertEqual(40.0, self.audit.realized_cash_eur("opp-whop-1"))
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-2"))
        self.assertTrue(self.audit.verify_audit_chain())

    def test_exact_replay_is_idempotent(self):
        first = attribute_cash_from_whop_bounty_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        second = attribute_cash_from_whop_bounty_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self.assertEqual(first, second)
        self.assertEqual(40.0, self.audit.realized_cash_eur("opp-whop-1"))

    def test_unknown_submission_is_rejected_before_attribution(self):
        with self.assertRaisesRegex(ValueError, "not proven provenance"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(submission_reference="btys_unknown123"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-1"))

    def test_receipt_reference_must_match_payout_event(self):
        with self.assertRaisesRegex(ValueError, "does not match payout event"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(payout_event_id="different-payout"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-1"))

    def test_wrong_receipt_platform_is_rejected_before_audit_attribution(self):
        self.audit.record_cash(
            CashReceipt(
                receipt_id="receipt-other",
                source_platform="cliparmy",
                amount_eur=10.0,
                received_at="2026-08-24T12:10:00+00:00",
                external_reference="payout-other",
            )
        )
        with self.assertRaisesRegex(ValueError, "source_platform must be whop_bounties"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(
                    payout_event_id="payout-other",
                    receipt_id="receipt-other",
                ),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-1"))

    def test_submission_success_alone_never_creates_cash(self):
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-1"))
        with self.assertRaisesRegex(ValueError, "cash receipt does not exist"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(receipt_id="missing-receipt"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-1"))

    def test_malformed_evidence_digest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(evidence_sha256="BAD"),
            )

    def test_one_payout_event_cannot_be_rebound_to_another_submission(self):
        attribute_cash_from_whop_bounty_evidence(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self._evidence(),
        )
        self._record_submission(
            opportunity_id="opp-whop-2",
            key="whop-bounty:job-2",
            reference="btys_submission456",
            job_id=2,
        )
        with self.assertRaisesRegex(ValueError, "event_id already exists with different content"):
            attribute_cash_from_whop_bounty_evidence(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                evidence=self._evidence(submission_reference="btys_submission456"),
            )
        self.assertEqual(0.0, self.audit.realized_cash_eur("opp-whop-2"))


if __name__ == "__main__":
    unittest.main()
