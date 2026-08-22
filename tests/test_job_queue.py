import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.job_queue import JobQueue


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = JobQueue(Path(self.tmp.name) / "workflow-os.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def _enqueue(self, *, max_attempts=3):
        return self.queue.enqueue(
            idempotency_key="job-1",
            opportunity_id="op-1",
            job_type="produce_clip",
            payload={"clip_id": "c1"},
            available_at="2026-08-22T10:00:00+00:00",
            max_attempts=max_attempts,
        )

    def test_enqueue_is_idempotent(self):
        self.assertEqual(self._enqueue(), self._enqueue())

    def test_idempotency_key_rejects_retry_budget_drift(self):
        self._enqueue(max_attempts=3)
        with self.assertRaises(ValueError):
            self._enqueue(max_attempts=4)

    def test_claim_and_complete_require_live_lease_owner(self):
        self._enqueue()
        job = self.queue.claim(
            worker_id="worker-a",
            now="2026-08-22T10:00:00+00:00",
            lease_seconds=60,
        )
        self.assertEqual(job.state, "LEASED")
        self.assertEqual(job.attempt_count, 1)
        with self.assertRaises(RuntimeError):
            self.queue.complete(
                job.job_id,
                worker_id="worker-b",
                now="2026-08-22T10:00:30+00:00",
            )
        self.assertEqual(
            self.queue.complete(
                job.job_id,
                worker_id="worker-a",
                now="2026-08-22T10:00:30+00:00",
            ).state,
            "SUCCEEDED",
        )

    def test_expired_worker_cannot_complete_before_recovery_marks_lease(self):
        self._enqueue()
        job = self.queue.claim(
            worker_id="worker-a",
            now="2026-08-22T10:00:00+00:00",
            lease_seconds=60,
        )
        with self.assertRaises(RuntimeError):
            self.queue.complete(
                job.job_id,
                worker_id="worker-a",
                now="2026-08-22T10:01:00+00:00",
            )

    def test_expired_worker_cannot_record_failure(self):
        self._enqueue()
        job = self.queue.claim(
            worker_id="worker-a",
            now="2026-08-22T10:00:00+00:00",
            lease_seconds=60,
        )
        with self.assertRaises(RuntimeError):
            self.queue.fail(
                job.job_id,
                worker_id="worker-a",
                now="2026-08-22T10:01:00+00:00",
                retry_safe=True,
                error="late worker result",
            )

    def test_ambiguous_failure_never_auto_retries(self):
        self._enqueue()
        job = self.queue.claim(worker_id="worker-a", now="2026-08-22T10:00:00+00:00")
        unknown = self.queue.fail(
            job.job_id,
            worker_id="worker-a",
            now="2026-08-22T10:00:30+00:00",
            retry_safe=False,
            error="ambiguous timeout",
        )
        self.assertEqual(unknown.state, "UNKNOWN")
        self.assertIsNone(
            self.queue.claim(worker_id="worker-b", now="2026-08-22T11:00:00+00:00")
        )

    def test_expired_lease_is_unknown_without_not_applied_evidence(self):
        self._enqueue()
        job = self.queue.claim(
            worker_id="worker-a",
            now="2026-08-22T10:00:00+00:00",
            lease_seconds=60,
        )
        expired = self.queue.expire_lease(
            job.job_id,
            now="2026-08-22T10:01:00+00:00",
            definitely_not_applied=False,
        )
        self.assertEqual(expired.state, "UNKNOWN")

    def test_expired_lease_retries_only_with_not_applied_evidence(self):
        self._enqueue()
        job = self.queue.claim(
            worker_id="worker-a",
            now="2026-08-22T10:00:00+00:00",
            lease_seconds=60,
        )
        retryable = self.queue.expire_lease(
            job.job_id,
            now="2026-08-22T10:01:00+00:00",
            definitely_not_applied=True,
            retry_at="2026-08-22T10:02:00+00:00",
        )
        self.assertEqual(retryable.state, "FAILED_RETRYABLE")
        self.assertIsNone(
            self.queue.claim(worker_id="worker-b", now="2026-08-22T10:01:30+00:00")
        )
        retried = self.queue.claim(
            worker_id="worker-b", now="2026-08-22T10:02:00+00:00"
        )
        self.assertEqual(retried.attempt_count, 2)

    def test_retry_budget_exhaustion_becomes_dead(self):
        self._enqueue(max_attempts=1)
        job = self.queue.claim(worker_id="worker-a", now="2026-08-22T10:00:00+00:00")
        dead = self.queue.fail(
            job.job_id,
            worker_id="worker-a",
            now="2026-08-22T10:00:30+00:00",
            retry_safe=True,
            error="safe compute failure",
        )
        self.assertEqual(dead.state, "DEAD")

    def test_naive_time_fails_closed(self):
        with self.assertRaises(ValueError):
            self.queue.enqueue(
                idempotency_key="bad-time",
                opportunity_id="op-1",
                job_type="produce_clip",
                payload={},
                available_at="2026-08-22T10:00:00",
            )


if __name__ == "__main__":
    unittest.main()
