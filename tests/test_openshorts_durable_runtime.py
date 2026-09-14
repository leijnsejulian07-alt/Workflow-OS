from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.openshorts_durable_runtime import prepare_verified_durable_openshorts_job
from workflow_os.side_effects import SideEffectLedger


def _verified_job(*, source_assets=None):
    opportunity = {
        "opportunity_id": "opp-1",
        "rights_verification_state": "VERIFIED",
        "usage_rights": "licensed campaign assets",
        "expected_owner_minutes": 0.0,
        "expected_net_profit": 12.5,
        "source_assets": source_assets if source_assets is not None else ["https://youtu.be/abc"],
    }
    record = JobRecord(
        7, "job-key", "opp-1", "produce_and_publish", "a" * 64,
        "LEASED", 1, 3, "2026-09-14T00:00:00+00:00", None, "worker", None,
    )
    return VerifiedLeasedOpportunityJob(record, {}, opportunity)


class OpenShortsDurableRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "side.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def prepare(self, job=None, **kwargs):
        params = {
            "webhook_url": "https://hooks.example.com/openshorts",
            "allowed_source_hosts": ["youtu.be"],
            "allowed_webhook_hosts": ["hooks.example.com"],
            "credential_authority_verified": True,
            "cost_authority_verified": True,
            "ledger": self.ledger,
        }
        params.update(kwargs)
        return prepare_verified_durable_openshorts_job(job or _verified_job(), **params)

    def test_resolves_verified_source_and_reserves_deterministically(self) -> None:
        prepared = self.prepare()
        self.assertEqual(prepared.source_url, "https://youtu.be/abc")
        self.assertEqual(prepared.webhook_url, "https://hooks.example.com/openshorts")
        replay = self.prepare()
        self.assertEqual(replay.reservation.request_fingerprint, prepared.reservation.request_fingerprint)

    def test_rejects_missing_or_ambiguous_source_assets(self) -> None:
        for assets in ([], ["https://youtu.be/a", "https://youtu.be/b"]):
            with self.subTest(assets=assets):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    self.prepare(_verified_job(source_assets=assets))

    def test_rejects_source_outside_allowlist(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "allowlisted"):
            self.prepare(_verified_job(source_assets=["https://evil.example/video"]))

    def test_rejects_non_https_and_ip_literal_sources(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            self.prepare(_verified_job(source_assets=["http://youtu.be/abc"]))
        with self.assertRaisesRegex(RuntimeError, "IP literal"):
            self.prepare(
                _verified_job(source_assets=["https://127.0.0.1/video"]),
                allowed_source_hosts=["127.0.0.1"],
            )

    def test_rejects_unapproved_webhook_host_before_reservation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "allowlisted"):
            self.prepare(webhook_url="https://other.example/openshorts")
        self.assertEqual(self.ledger.list_records(), [])

    def test_still_requires_provider_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential authority"):
            self.prepare(credential_authority_verified=False)


if __name__ == "__main__":
    unittest.main()
