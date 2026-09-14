from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from workflow_os.openshorts_worker_cycle import run_bounded_openshorts_worker_cycle


class OpenShortsWorkerCycleTests(unittest.TestCase):
    @patch("workflow_os.openshorts_worker_cycle.run_one_durable_openshorts_job")
    def test_stops_immediately_when_queue_is_empty(self, run_one) -> None:
        run_one.return_value = None

        result = run_bounded_openshorts_worker_cycle(max_jobs=4, sentinel="x")

        self.assertEqual(0, result.attempted)
        self.assertEqual(0, result.completed)
        self.assertTrue(result.stopped_on_empty_queue)
        run_one.assert_called_once_with(sentinel="x")

    @patch("workflow_os.openshorts_worker_cycle.run_one_durable_openshorts_job")
    def test_processes_jobs_sequentially_up_to_bound(self, run_one) -> None:
        run_one.side_effect = [
            SimpleNamespace(job=SimpleNamespace(state="SUCCEEDED")),
            SimpleNamespace(job=SimpleNamespace(state="SUCCEEDED")),
            SimpleNamespace(job=SimpleNamespace(state="SUCCEEDED")),
        ]

        result = run_bounded_openshorts_worker_cycle(max_jobs=3, sentinel="x")

        self.assertEqual(3, result.attempted)
        self.assertEqual(3, result.completed)
        self.assertFalse(result.stopped_on_empty_queue)
        self.assertEqual(3, run_one.call_count)

    @patch("workflow_os.openshorts_worker_cycle.run_one_durable_openshorts_job")
    def test_stops_after_first_empty_result_without_extra_polling(self, run_one) -> None:
        run_one.side_effect = [
            SimpleNamespace(job=SimpleNamespace(state="SUCCEEDED")),
            None,
        ]

        result = run_bounded_openshorts_worker_cycle(max_jobs=4)

        self.assertEqual(1, result.attempted)
        self.assertEqual(1, result.completed)
        self.assertTrue(result.stopped_on_empty_queue)
        self.assertEqual(2, run_one.call_count)

    def test_rejects_unbounded_or_invalid_cycle_sizes(self) -> None:
        for value in (0, 5, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    run_bounded_openshorts_worker_cycle(max_jobs=value)


if __name__ == "__main__":
    unittest.main()
