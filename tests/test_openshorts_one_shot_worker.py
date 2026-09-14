from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.openshorts_hosted import OpenShortsProcessResult
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_one_shot_worker import run_one_durable_openshorts_job
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-09-14T10:00:00+00:00"


class _FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    def process_video(self, **kwargs):
        self.calls.append(kwargs)
        return OpenShortsProcessResult(job_id="os-one-shot-1", response_sha256="d" * 64)


class OpenShortsOneShotWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.transport = _FakeTransport()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _enqueue(self, *, source_asset: str = "https://youtu.be/abc"):
        opportunity = {
            "opportunity_id": "opp-one-shot-1",
            "rights_verification_state": "VERIFIED",
            "usage_rights": "licensed campaign assets",
            "expected_owner_minutes": 0.0,
            "expected_net_profit": 12.5,
            "source_assets": [source_asset],
        }
        canonical = json.dumps(
            opportunity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        payload = {
            "opportunity_id": "opp-one-shot-1",
            "batch_fingerprint": "b" * 64,
            "batch_slot": 1,
            "opportunity_snapshot": opportunity,
            "opportunity_snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
            "revenue_control": {
                "opportunity_id": "opp-one-shot-1",
                "may_schedule": True,
            },
        }
        return self.queue.enqueue(
            idempotency_key="job-one-shot-1",
            opportunity_id="opp-one-shot-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )

    def _run(self):
        return run_one_durable_openshorts_job(
            queue=self.queue,
            side_effect_ledger=self.effects,
            worker_id="openshorts-worker-1",
            now=NOW,
            webhook_url="https://hooks.example.com/openshorts",
            allowed_source_hosts=("youtu.be",),
            allowed_webhook_hosts=("hooks.example.com",),
            credential_authority_verified=True,
            cost_authority_verified=True,
            transport=self.transport,
            api_key="osk_test_123456789",
            webhook_secret="x" * 32,
        )

    def test_claim_prepare_dispatch_and_reconcile_complete_one_job(self) -> None:
        self._enqueue()

        result = self._run()

        self.assertIsNotNone(result)
        self.assertEqual("SUCCEEDED", result.job.state)
        self.assertEqual("SUCCEEDED", result.side_effect.state)
        self.assertEqual("os-one-shot-1", result.side_effect.external_reference)
        self.assertEqual(1, len(self.transport.calls))
        self.assertEqual("https://youtu.be/abc", self.transport.calls[0]["source_url"])

    def test_empty_queue_performs_no_external_work(self) -> None:
        result = self._run()

        self.assertIsNone(result)
        self.assertEqual([], self.transport.calls)

    def test_pre_dispatch_config_failure_is_persisted_retry_safe(self) -> None:
        self._enqueue(source_asset="https://untrusted.example/video")

        with self.assertRaisesRegex(RuntimeError, "pre-dispatch preparation"):
            self._run()

        self.assertEqual([], self.transport.calls)
        retry = self.queue.claim(worker_id="retry-worker", now=NOW, lease_seconds=300)
        self.assertIsNotNone(retry)
        self.assertEqual(2, retry.attempt_count)
        self.assertEqual("LEASED", retry.state)


if __name__ == "__main__":
    unittest.main()
