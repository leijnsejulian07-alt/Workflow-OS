from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.whop_bounty_submission import WhopBountyDeliverable
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_job_preparation import prepare_durable_whop_bounty_submission


class DurableWhopBountyPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, **op_overrides):
        opportunity = {
            "opportunity_id": "opp-whop-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_example123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
            "zero_touch_execution_enabled": True,
            "rights_verification_state": "VERIFIED",
            "account_authorized": True,
            "worker_identity_verified": True,
            "campaign_requirements_verified": True,
            "deliverable_requirements_verified": True,
        }
        opportunity.update(op_overrides)
        record = JobRecord(
            job_id=7,
            idempotency_key="revenue:example:1",
            opportunity_id="opp-whop-1",
            job_type="produce_and_publish",
            request_fingerprint="a" * 64,
            state="LEASED",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-08-24T06:00:00+00:00",
            lease_expires_at="2026-08-24T06:05:00+00:00",
            worker_id="worker-1",
            last_error=None,
        )
        return VerifiedLeasedOpportunityJob(job=record, payload={}, opportunity=opportunity)

    @staticmethod
    def _deliverable(url="https://example.com/result/1"):
        return WhopBountyDeliverable(deliverable_type="content_url", urls=(url,))

    def _count_effects(self):
        with sqlite3.connect(self.ledger.path) as db:
            return db.execute("SELECT COUNT(*) FROM side_effects").fetchone()[0]

    def test_prepares_one_job_bound_reservation(self):
        prepared = prepare_durable_whop_bounty_submission(
            self._job(),
            self._deliverable(),
            deliverable_verified=True,
            ledger=self.ledger,
        )

        self.assertEqual(prepared.job_id, 7)
        self.assertEqual(prepared.opportunity_id, "opp-whop-1")
        self.assertEqual(prepared.reservation.bounty_id, "bnty_example123")
        self.assertEqual(prepared.reservation.side_effect.state, "RESERVED")
        self.assertTrue(prepared.reservation.idempotency_key.startswith("whopjob:7:"))
        self.assertEqual(self._count_effects(), 1)

    def test_exact_replay_is_idempotent(self):
        first = prepare_durable_whop_bounty_submission(
            self._job(), self._deliverable(), deliverable_verified=True, ledger=self.ledger
        )
        second = prepare_durable_whop_bounty_submission(
            self._job(), self._deliverable(), deliverable_verified=True, ledger=self.ledger
        )

        self.assertEqual(first.reservation.idempotency_key, second.reservation.idempotency_key)
        self.assertEqual(
            first.reservation.side_effect.request_fingerprint,
            second.reservation.side_effect.request_fingerprint,
        )
        self.assertEqual(self._count_effects(), 1)

    def test_same_durable_job_cannot_be_rebound_to_different_deliverable(self):
        prepare_durable_whop_bounty_submission(
            self._job(), self._deliverable(), deliverable_verified=True, ledger=self.ledger
        )
        with self.assertRaises(ValueError):
            prepare_durable_whop_bounty_submission(
                self._job(),
                self._deliverable("https://example.com/result/2"),
                deliverable_verified=True,
                ledger=self.ledger,
            )
        self.assertEqual(self._count_effects(), 1)

    def test_unverified_deliverable_stops_before_reservation(self):
        with self.assertRaises(ValueError):
            prepare_durable_whop_bounty_submission(
                self._job(), self._deliverable(), deliverable_verified=False, ledger=self.ledger
            )
        self.assertEqual(self._count_effects(), 0)

    def test_opportunity_owned_authority_must_be_verified(self):
        fields = (
            ("machine_submission_verified", False),
            ("zero_touch_execution_enabled", False),
            ("rights_verification_state", "UNKNOWN"),
            ("account_authorized", False),
            ("worker_identity_verified", False),
            ("campaign_requirements_verified", False),
            ("deliverable_requirements_verified", False),
        )
        for field, value in fields:
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    prepare_durable_whop_bounty_submission(
                        self._job(**{field: value}),
                        self._deliverable(),
                        deliverable_verified=True,
                        ledger=self.ledger,
                    )
                self.assertEqual(self._count_effects(), 0)

    def test_non_whop_and_non_workforce_jobs_fail_closed(self):
        for overrides in (
            {"source_platform": "whop_content_rewards"},
            {"bounty_type": "classic"},
            {"campaign_id": "not-a-bounty"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(RuntimeError):
                    prepare_durable_whop_bounty_submission(
                        self._job(**overrides),
                        self._deliverable(),
                        deliverable_verified=True,
                        ledger=self.ledger,
                    )
                self.assertEqual(self._count_effects(), 0)

    def test_invalid_deliverable_is_rejected_by_existing_submission_contract(self):
        with self.assertRaises(ValueError):
            prepare_durable_whop_bounty_submission(
                self._job(),
                WhopBountyDeliverable(deliverable_type="content_url", urls=("http://unsafe.test/x",)),
                deliverable_verified=True,
                ledger=self.ledger,
            )
        self.assertEqual(self._count_effects(), 0)


if __name__ == "__main__":
    unittest.main()
