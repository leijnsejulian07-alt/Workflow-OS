from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.openshorts_job_preparation import prepare_durable_openshorts_processing
from workflow_os.side_effects import SideEffectLedger


def _verified_job(**op_overrides):
    opportunity = {
        "opportunity_id": "opp-1",
        "rights_verification_state": "VERIFIED",
        "usage_rights": "licensed campaign assets",
        "expected_owner_minutes": 0.0,
        "expected_net_profit": 12.5,
    }
    opportunity.update(op_overrides)
    record = JobRecord(7, "job-key", "opp-1", "produce_and_publish", "a" * 64,
                       "LEASED", 1, 3, "2026-09-13T00:00:00+00:00", None, "worker", None)
    return VerifiedLeasedOpportunityJob(record, {}, opportunity)


class OpenShortsPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "side.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prepare(self, job=None, **kwargs):
        source_url = kwargs.pop("source_url", "https://youtu.be/abc")
        webhook_url = kwargs.pop("webhook_url", "https://hooks.example.com/openshorts")
        return prepare_durable_openshorts_processing(
            job or _verified_job(), source_url=source_url, webhook_url=webhook_url,
            credential_authority_verified=True, cost_authority_verified=True,
            ledger=self.ledger, **kwargs,
        )

    def test_reserves_deterministic_secret_free_side_effect(self) -> None:
        prepared = self.prepare()
        self.assertEqual(prepared.reservation.action, "openshorts.process")
        self.assertEqual(prepared.reservation.state, "RESERVED")
        replay = self.prepare()
        self.assertEqual(replay.reservation.request_fingerprint, prepared.reservation.request_fingerprint)

    def test_rejects_unverified_rights(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rights"):
            self.prepare(_verified_job(rights_verification_state="UNKNOWN"))

    def test_rejects_recurring_owner_work(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "owner work"):
            self.prepare(_verified_job(expected_owner_minutes=1.0))

    def test_rejects_non_positive_margin(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "margin"):
            self.prepare(_verified_job(expected_net_profit=0.0))

    def test_requires_cost_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "cost authority"):
            prepare_durable_openshorts_processing(
                _verified_job(), source_url="https://youtu.be/abc",
                webhook_url="https://hooks.example.com/openshorts",
                credential_authority_verified=True, cost_authority_verified=False,
                ledger=self.ledger,
            )

    def test_changed_source_conflicts_for_same_durable_job(self) -> None:
        self.prepare()
        with self.assertRaisesRegex(ValueError, "different side effect"):
            self.prepare(source_url="https://youtu.be/different")


if __name__ == "__main__":
    unittest.main()
