from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.openshorts_execution import OpenShortsExecutionEvidenceStore
from workflow_os.openshorts_status_runtime_entrypoint import (
    run_bounded_openshorts_terminal_reconciliation,
)
from workflow_os.side_effects import SideEffectLedger


class _FakeTransport:
    def __init__(self, statuses: dict[str, str]):
        self.statuses = statuses
        self.calls: list[str] = []

    def get_status(self, *, api_key: str, job_id: str):
        if api_key != "osk_test_status_runtime":
            raise AssertionError("unexpected API key")
        self.calls.append(job_id)
        return {"job_id": job_id, "status": self.statuses[job_id]}


class OpenShortsStatusRuntimeEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "workflow.sqlite3")
        self.ledger = SideEffectLedger(self.db_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _confirmed_dispatch(self, key: str, job_id: str) -> None:
        self.ledger.reserve(
            idempotency_key=key,
            action="openshorts.process",
            target="https://api.openshorts.app/api/process",
            payload={"source": key},
            max_attempts=2,
        )
        self.ledger.begin_attempt(key)
        self.ledger.mark_succeeded(key, external_reference=job_id)

    def test_completed_provider_job_becomes_terminal_evidence(self) -> None:
        self._confirmed_dispatch("render:1", "job-1")
        transport = _FakeTransport({"job-1": "completed"})

        result = run_bounded_openshorts_terminal_reconciliation(
            state_db_path=self.db_path,
            api_key="osk_test_status_runtime",
            max_checks=1,
            transport=transport,
        )

        self.assertEqual((result.checked, result.terminal, result.pending), (1, 1, 0))
        self.assertEqual(transport.calls, ["job-1"])
        evidence = OpenShortsExecutionEvidenceStore(self.db_path).get("render:1")
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence.provider_job_id, "job-1")
        self.assertEqual(evidence.terminal_state, "COMPLETED")
        self.assertEqual(evidence.source, "status_api")

    def test_nonterminal_provider_job_is_left_for_later_cycle(self) -> None:
        self._confirmed_dispatch("render:pending", "job-pending")
        transport = _FakeTransport({"job-pending": "processing"})

        result = run_bounded_openshorts_terminal_reconciliation(
            state_db_path=self.db_path,
            api_key="osk_test_status_runtime",
            max_checks=1,
            transport=transport,
        )

        self.assertEqual((result.checked, result.terminal, result.pending), (1, 0, 1))
        self.assertIsNone(OpenShortsExecutionEvidenceStore(self.db_path).get("render:pending"))

    def test_cycle_is_bounded_and_skips_already_reconciled_jobs(self) -> None:
        self._confirmed_dispatch("render:a", "job-a")
        self._confirmed_dispatch("render:b", "job-b")
        self._confirmed_dispatch("render:c", "job-c")
        transport = _FakeTransport({"job-a": "completed", "job-b": "failed", "job-c": "completed"})

        first = run_bounded_openshorts_terminal_reconciliation(
            state_db_path=self.db_path,
            api_key="osk_test_status_runtime",
            max_checks=2,
            transport=transport,
        )
        second = run_bounded_openshorts_terminal_reconciliation(
            state_db_path=self.db_path,
            api_key="osk_test_status_runtime",
            max_checks=2,
            transport=transport,
        )

        self.assertEqual((first.checked, first.terminal, first.pending), (2, 2, 0))
        self.assertEqual((second.checked, second.terminal, second.pending), (1, 1, 0))
        self.assertEqual(transport.calls, ["job-a", "job-b", "job-c"])

    def test_invalid_cycle_bound_fails_before_provider_calls(self) -> None:
        transport = _FakeTransport({})
        with self.assertRaises(ValueError):
            run_bounded_openshorts_terminal_reconciliation(
                state_db_path=self.db_path,
                api_key="osk_test_status_runtime",
                max_checks=5,
                transport=transport,
            )
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
