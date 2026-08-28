import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.durable_worker import claim_verified_opportunity_job
from workflow_os.job_queue import JobQueue


class DurableWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "workflow-os.sqlite3"
        self.queue = JobQueue(self.db_path)
        self.snapshot = {
            "opportunity_id": "op-1",
            "source_platform": "cliparmy",
            "campaign_id": "campaign-1",
            "title": "Authorized campaign",
        }
        canonical = json.dumps(
            self.snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.snapshot_sha = hashlib.sha256(canonical).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def _payload(self):
        return {
            "opportunity_id": "op-1",
            "opportunity_snapshot": self.snapshot,
            "opportunity_snapshot_sha256": self.snapshot_sha,
            "batch_fingerprint": "a" * 64,
            "batch_slot": 1,
            "revenue_control": {
                "opportunity_id": "op-1",
                "action": "KEEP",
                "may_schedule": True,
                "max_new_jobs": 1,
            },
        }

    def _enqueue(self, *, job_type="produce_and_publish", payload=None, max_attempts=3):
        return self.queue.enqueue(
            idempotency_key="revenue:test:1",
            opportunity_id="op-1",
            job_type=job_type,
            payload=self._payload() if payload is None else payload,
            available_at="2026-08-22T18:00:00+00:00",
            max_attempts=max_attempts,
        )

    def _state(self, job_id):
        with managed_connection(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                "SELECT state,attempt_count,last_error FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return row

    def test_claim_returns_verified_snapshot_and_live_job(self):
        job = self._enqueue()
        verified = claim_verified_opportunity_job(
            self.queue,
            worker_id="worker-1",
            now="2026-08-22T18:00:01+00:00",
        )
        self.assertIsNotNone(verified)
        self.assertEqual(verified.job.job_id, job.job_id)
        self.assertEqual(verified.opportunity, self.snapshot)
        self.assertIsNot(verified.opportunity, self.snapshot)
        self.assertEqual(self._state(job.job_id)[0], "LEASED")

    def test_invalid_snapshot_is_retry_safe_before_any_side_effect(self):
        payload = self._payload()
        payload["opportunity_snapshot_sha256"] = "0" * 64
        job = self._enqueue(payload=payload)
        with self.assertRaises(RuntimeError):
            claim_verified_opportunity_job(
                self.queue,
                worker_id="worker-1",
                now="2026-08-22T18:00:01+00:00",
            )
        state, attempts, error = self._state(job.job_id)
        self.assertEqual(state, "FAILED_RETRYABLE")
        self.assertEqual(attempts, 1)
        self.assertEqual(error, "pre-execution durable job validation failed")

    def test_persistent_corruption_becomes_dead_at_retry_budget(self):
        payload = self._payload()
        payload["batch_fingerprint"] = "not-a-digest"
        job = self._enqueue(payload=payload, max_attempts=1)
        with self.assertRaises(RuntimeError):
            claim_verified_opportunity_job(
                self.queue,
                worker_id="worker-1",
                now="2026-08-22T18:00:01+00:00",
            )
        self.assertEqual(self._state(job.job_id)[0], "DEAD")

    def test_unsupported_job_type_fails_before_execution(self):
        job = self._enqueue(job_type="unknown_side_effect")
        with self.assertRaises(RuntimeError):
            claim_verified_opportunity_job(
                self.queue,
                worker_id="worker-1",
                now="2026-08-22T18:00:01+00:00",
            )
        self.assertEqual(self._state(job.job_id)[0], "FAILED_RETRYABLE")

    def test_mutated_persisted_payload_is_caught_by_queue_fingerprint(self):
        job = self._enqueue()
        with managed_connection(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "UPDATE jobs SET request_json=? WHERE job_id=?",
                (json.dumps({"opportunity_id": "op-1", "tampered": True}), job.job_id),
            )
        with self.assertRaises(RuntimeError):
            claim_verified_opportunity_job(
                self.queue,
                worker_id="worker-1",
                now="2026-08-22T18:00:01+00:00",
            )
        self.assertEqual(self._state(job.job_id)[0], "FAILED_RETRYABLE")

    def test_empty_queue_returns_none(self):
        self.assertIsNone(
            claim_verified_opportunity_job(
                self.queue,
                worker_id="worker-1",
                now="2026-08-22T18:00:01+00:00",
            )
        )


if __name__ == "__main__":
    unittest.main()
