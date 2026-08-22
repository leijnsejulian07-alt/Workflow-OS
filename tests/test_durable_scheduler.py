import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.durable_scheduler import enqueue_controlled_candidates
from workflow_os.job_queue import JobQueue


class DurableRevenueSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = JobQueue(Path(self.tmp.name) / "workflow-os.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _candidate(*, action="KEEP", jobs=1, samples=1, profit=15.0):
        return {
            "opportunity_id": "op-1",
            "decision": "ACCEPT",
            "eligible_for_queue": True,
            "revenue_control": {
                "opportunity_id": "op-1",
                "action": action,
                "may_schedule": True,
                "max_new_jobs": jobs,
                "reasons": ["REALIZED_PROFIT_POSITIVE"],
                "realized_cash_eur": 20.0,
                "reconciled_cost_eur": 5.0,
                "realized_profit_eur": profit,
                "sample_count": samples,
                "policy_version": "reconciled-scaling-control/2",
            },
        }

    def test_same_reconciled_state_is_idempotent(self):
        candidate = self._candidate()
        first = enqueue_controlled_candidates(
            self.queue, [candidate], scheduled_at="2026-08-22T12:00:00+00:00"
        )
        second = enqueue_controlled_candidates(
            self.queue, [candidate], scheduled_at="2026-08-22T12:05:00+00:00"
        )
        self.assertEqual([job.job_id for job in first], [job.job_id for job in second])

    def test_scale_creates_bounded_distinct_slots(self):
        queued = enqueue_controlled_candidates(
            self.queue,
            [self._candidate(action="SCALE", jobs=3, samples=4, profit=55.0)],
            scheduled_at="2026-08-22T12:00:00+00:00",
        )
        self.assertEqual(len(queued), 3)
        self.assertEqual(len({job.idempotency_key for job in queued}), 3)

    def test_new_reconciled_state_creates_new_batch(self):
        first = enqueue_controlled_candidates(
            self.queue,
            [self._candidate(samples=1, profit=15.0)],
            scheduled_at="2026-08-22T12:00:00+00:00",
        )
        second = enqueue_controlled_candidates(
            self.queue,
            [self._candidate(samples=2, profit=30.0)],
            scheduled_at="2026-08-22T12:05:00+00:00",
        )
        self.assertNotEqual(first[0].job_id, second[0].job_id)

    def test_non_schedulable_or_unbounded_candidate_fails_closed(self):
        candidate = self._candidate()
        candidate["revenue_control"]["may_schedule"] = False
        with self.assertRaises(RuntimeError):
            enqueue_controlled_candidates(
                self.queue, [candidate], scheduled_at="2026-08-22T12:00:00+00:00"
            )

        candidate = self._candidate()
        candidate["revenue_control"]["max_new_jobs"] = 5
        with self.assertRaises(RuntimeError):
            enqueue_controlled_candidates(
                self.queue, [candidate], scheduled_at="2026-08-22T12:00:00+00:00"
            )

    def test_upstream_eligibility_cannot_be_overridden(self):
        candidate = self._candidate()
        candidate["eligible_for_queue"] = False
        with self.assertRaises(RuntimeError):
            enqueue_controlled_candidates(
                self.queue, [candidate], scheduled_at="2026-08-22T12:00:00+00:00"
            )

    def test_changed_retry_budget_conflicts_with_same_batch(self):
        candidate = self._candidate()
        enqueue_controlled_candidates(
            self.queue,
            [candidate],
            scheduled_at="2026-08-22T12:00:00+00:00",
            max_attempts=2,
        )
        with self.assertRaises(ValueError):
            enqueue_controlled_candidates(
                self.queue,
                [candidate],
                scheduled_at="2026-08-22T12:05:00+00:00",
                max_attempts=3,
            )


if __name__ == "__main__":
    unittest.main()
