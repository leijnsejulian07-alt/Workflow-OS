from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from workflow_os.adapters.whop_bounty_submission import WhopBountyDeliverable
from workflow_os.audit import AuditRevenueLedger
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_whop_handoff import PreparedOpenShortsWhopDeliverable
from workflow_os.openshorts_whop_reservation import reserve_verified_openshorts_whop_submission
from workflow_os.openshorts_whop_settlement import (
    reconcile_prepared_openshorts_whop_payout_and_decide_next_action,
)
from workflow_os.reconciliation import RevenueReconciliationLedger
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from workflow_os.whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)

NOW = "2026-09-14T00:00:00+00:00"


class OpenShortsWhopSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        self.reconciliation = RevenueReconciliationLedger(root / "reconciliation.sqlite")
        payload = {"opportunity_id": "opp-open-settle-1", "campaign_id": "bnty_open123"}
        self.queue.enqueue(
            idempotency_key="job-open-settle-1",
            opportunity_id="opp-open-settle-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-open-1", now=NOW, lease_seconds=300)
        self.job = VerifiedLeasedOpportunityJob(
            job=leased,
            payload=payload,
            opportunity={
                "opportunity_id": "opp-open-settle-1",
                "source_platform": "whop_bounties",
                "campaign_id": "bnty_open123",
                "bounty_type": "workforce",
                "machine_submission_verified": True,
                "zero_touch_execution_enabled": True,
                "rights_verification_state": "VERIFIED",
                "account_authorized": True,
                "worker_identity_verified": True,
                "campaign_requirements_verified": True,
                "deliverable_requirements_verified": True,
            },
        )
        handoff = PreparedOpenShortsWhopDeliverable(
            opportunity_id="opp-open-settle-1",
            openshorts_idempotency_key=f"openshorts:{leased.job_id}:" + "b" * 64,
            provider_job_id="job_open_123",
            clip_index=0,
            evidence_sha256="c" * 64,
            deliverable=WhopBountyDeliverable(deliverable_type="content_url", urls=("https://cdn.example.com/clip.mp4",)),
        )
        self.prepared = reserve_verified_openshorts_whop_submission(
            self.job,
            handoff,
            credential_authority_verified=True,
            ledger=self.effects,
        )
        side_effect = self.prepared.submission.reservation.side_effect
        self.provenance_record = WhopBountySubmissionProvenance(
            opportunity_id="opp-open-settle-1",
            bounty_id="bnty_open123",
            side_effect_idempotency_key=side_effect.idempotency_key,
            side_effect_request_fingerprint=side_effect.request_fingerprint,
            submission_target="https://api.whop.com/api/v1/bounty_submissions",
            submission_reference="btys_open123",
        )
        self.evidence = WhopBountyPayoutEvidence(
            payout_event_id="payout-open-1",
            receipt_id="receipt-open-1",
            submission_reference="btys_open123",
            evidence_sha256="d" * 64,
        )

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("workflow_os.openshorts_whop_settlement.reconcile_whop_bounty_payout_and_decide_next_action")
    def test_exact_openshorts_submission_may_enter_reconciled_cash_feedback(self, settle):
        settle.return_value = SimpleNamespace(
            payout=SimpleNamespace(provenance=self.provenance_record),
            scaling=SimpleNamespace(action="KEEP"),
        )
        with mock.patch.object(self.provenance, "get_by_reference", return_value=self.provenance_record):
            result = reconcile_prepared_openshorts_whop_payout_and_decide_next_action(
                self.prepared,
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="e" * 64,
            )
        self.assertEqual(self.provenance_record, result.provenance)
        self.assertEqual("KEEP", result.settlement.scaling.action)
        settle.assert_called_once()

    @mock.patch("workflow_os.openshorts_whop_settlement.reconcile_whop_bounty_payout_and_decide_next_action")
    def test_mismatched_submission_side_effect_fails_before_cash_reconciliation(self, settle):
        drifted = replace(self.provenance_record, side_effect_idempotency_key="whopjob:999:drift")
        with mock.patch.object(self.provenance, "get_by_reference", return_value=drifted):
            with self.assertRaisesRegex(RuntimeError, "side effect"):
                reconcile_prepared_openshorts_whop_payout_and_decide_next_action(
                    self.prepared,
                    audit_ledger=self.audit,
                    provenance_ledger=self.provenance,
                    reconciliation_ledger=self.reconciliation,
                    evidence=self.evidence,
                    settlement_evidence_sha256="e" * 64,
                )
        settle.assert_not_called()

    @mock.patch("workflow_os.openshorts_whop_settlement.reconcile_whop_bounty_payout_and_decide_next_action")
    def test_unproven_submission_fails_closed(self, settle):
        with mock.patch.object(self.provenance, "get_by_reference", return_value=None):
            with self.assertRaisesRegex(ValueError, "no proven provenance"):
                reconcile_prepared_openshorts_whop_payout_and_decide_next_action(
                    self.prepared,
                    audit_ledger=self.audit,
                    provenance_ledger=self.provenance,
                    reconciliation_ledger=self.reconciliation,
                    evidence=self.evidence,
                    settlement_evidence_sha256="e" * 64,
                )
        settle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
