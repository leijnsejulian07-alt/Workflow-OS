from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_execution import OpenShortsExecutionEvidenceStore
from workflow_os.openshorts_status_runtime_entrypoint import run_bounded_openshorts_terminal_reconciliation
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-09-14T20:45:00+00:00"


class _CompletedTransport:
    def get_status(self, *, api_key: str, job_id: str):
        if api_key != "osk_integration":
            raise AssertionError("unexpected API key")
        return {
            "job_id": job_id,
            "status": "completed",
            "result": {
                "clips": [{
                    "title": "Ready clip",
                    "video_url": f"/api/files/{job_id}/clip-0.mp4",
                }]
            },
        }


class OpenShortsStatusEnqueueIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "workflow.sqlite3")
        self.queue = JobQueue(self.db_path)
        self.ledger = SideEffectLedger(self.db_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _source_job(self, *, complete: bool = True):
        source = self.queue.enqueue(
            idempotency_key="source-render",
            opportunity_id="opp-1",
            job_type="produce_and_publish",
            payload={
                "opportunity_id": "opp-1",
                "batch_fingerprint": "a" * 64,
                "opportunity_snapshot": {"opportunity_id": "opp-1"},
                "opportunity_snapshot_sha256": "b" * 64,
                "revenue_control": {"opportunity_id": "opp-1", "may_schedule": True},
                "batch_slot": 1,
            },
            available_at=NOW,
        )
        leased = self.queue.claim(worker_id="render-worker", now=NOW, allowed_job_types={"produce_and_publish"})
        assert leased is not None
        if complete:
            source = self.queue.complete(leased.job_id, worker_id="render-worker", now=NOW)
        else:
            source = leased
        digest = hashlib.sha256(
            f"openshorts-job\n{source.job_id}\n{source.request_fingerprint}".encode("utf-8")
        ).hexdigest()
        return source, f"openshorts:{source.job_id}:{digest}"

    def _confirmed_dispatch(self, key: str, provider_job_id: str) -> None:
        self.ledger.reserve(
            idempotency_key=key,
            action="openshorts.process",
            target="https://api.openshorts.app/api/process",
            payload={"source": "verified"},
            max_attempts=2,
        )
        self.ledger.begin_attempt(key)
        self.ledger.mark_succeeded(key, external_reference=provider_job_id)

    def test_completed_status_enqueues_separate_submit_reward_job_before_terminal_commit(self) -> None:
        source, key = self._source_job()
        self._confirmed_dispatch(key, "provider-1")

        result = run_bounded_openshorts_terminal_reconciliation(
            state_db_path=self.db_path,
            api_key="osk_integration",
            max_checks=1,
            transport=_CompletedTransport(),
            available_at=NOW,
        )

        self.assertEqual(result.outputs_recorded, 1)
        self.assertEqual(result.submission_jobs_enqueued, 1)
        self.assertIsNotNone(OpenShortsExecutionEvidenceStore(self.db_path).get(key))
        child = self.queue.claim(worker_id="whop-worker", now=NOW, allowed_job_types={"submit_reward"})
        self.assertIsNotNone(child)
        assert child is not None
        self.assertNotEqual(child.job_id, source.job_id)
        payload = self.queue.read_leased_payload(child.job_id, worker_id="whop-worker", now=NOW)
        self.assertEqual(payload["upstream_render"]["source_job_id"], source.job_id)
        self.assertEqual(payload["upstream_render"]["provider_job_id"], "provider-1")

    def test_child_enqueue_failure_does_not_commit_terminal_evidence(self) -> None:
        _source, key = self._source_job(complete=False)
        self._confirmed_dispatch(key, "provider-unsafe")

        with self.assertRaises(RuntimeError):
            run_bounded_openshorts_terminal_reconciliation(
                state_db_path=self.db_path,
                api_key="osk_integration",
                max_checks=1,
                transport=_CompletedTransport(),
                available_at=NOW,
            )

        self.assertIsNone(OpenShortsExecutionEvidenceStore(self.db_path).get(key))
        self.assertIsNone(self.queue.claim(worker_id="whop-worker", now=NOW, allowed_job_types={"submit_reward"}))


if __name__ == "__main__":
    unittest.main()
