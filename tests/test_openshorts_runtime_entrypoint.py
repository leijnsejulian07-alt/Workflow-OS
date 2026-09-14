from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_os.openshorts_runtime_entrypoint import (
    load_openshorts_runtime_config,
    run_openshorts_runtime_once,
)
from workflow_os.openshorts_worker_cycle import OpenShortsWorkerCycleResult


class OpenShortsRuntimeEntrypointTests(unittest.TestCase):
    def _env(self, db_path: str) -> dict[str, str]:
        return {
            "WORKFLOW_OS_OPENSHORTS_CREDENTIAL_AUTHORITY": "verified",
            "WORKFLOW_OS_OPENSHORTS_COST_AUTHORITY": "verified",
            "WORKFLOW_OS_OPENSHORTS_STATE_DB": db_path,
            "WORKFLOW_OS_OPENSHORTS_WORKER_ID": "openshorts-worker-1",
            "WORKFLOW_OS_OPENSHORTS_WEBHOOK_URL": "https://hooks.example.com/openshorts",
            "WORKFLOW_OS_OPENSHORTS_ALLOWED_SOURCE_HOSTS": "youtube.com,www.youtube.com,youtu.be",
            "WORKFLOW_OS_OPENSHORTS_ALLOWED_WEBHOOK_HOSTS": "hooks.example.com",
            "OPENSHORTS_API_KEY": "osk_test_key_12345",
            "WORKFLOW_OS_OPENSHORTS_WEBHOOK_SECRET": "s" * 32,
            "WORKFLOW_OS_OPENSHORTS_MAX_JOBS": "2",
            "WORKFLOW_OS_OPENSHORTS_LEASE_SECONDS": "300",
        }

    def test_loads_explicit_runtime_authority_without_persisting_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(str(Path(tmp, "workflow.sqlite").resolve()))
            config = load_openshorts_runtime_config(env)

        self.assertEqual(2, config.max_jobs)
        self.assertEqual(("youtube.com", "www.youtube.com", "youtu.be"), config.allowed_source_hosts)
        self.assertEqual(("hooks.example.com",), config.allowed_webhook_hosts)
        self.assertEqual("osk_test_key_12345", config.api_key)

    def test_rejects_missing_or_unverified_authority_before_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(str(Path(tmp, "workflow.sqlite").resolve()))
            env["WORKFLOW_OS_OPENSHORTS_COST_AUTHORITY"] = "true"
            with self.assertRaises(RuntimeError):
                load_openshorts_runtime_config(env)

            env = self._env(str(Path(tmp, "workflow.sqlite").resolve()))
            del env["OPENSHORTS_API_KEY"]
            with self.assertRaises(RuntimeError):
                load_openshorts_runtime_config(env)

    def test_rejects_unallowlisted_webhook_and_unbounded_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(str(Path(tmp, "workflow.sqlite").resolve()))
            env["WORKFLOW_OS_OPENSHORTS_WEBHOOK_URL"] = "https://evil.example/openshorts"
            with self.assertRaises(RuntimeError):
                load_openshorts_runtime_config(env)

            env = self._env(str(Path(tmp, "workflow.sqlite").resolve()))
            env["WORKFLOW_OS_OPENSHORTS_MAX_JOBS"] = "5"
            with self.assertRaises(RuntimeError):
                load_openshorts_runtime_config(env)

    @patch("workflow_os.openshorts_runtime_entrypoint.run_bounded_openshorts_worker_cycle")
    def test_runtime_composes_existing_queue_ledger_and_bounded_cycle(self, run_cycle) -> None:
        run_cycle.return_value = OpenShortsWorkerCycleResult(
            attempted=1,
            completed=1,
            stopped_on_empty_queue=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp, "workflow.sqlite").resolve())
            config = load_openshorts_runtime_config(self._env(db_path))
            result = run_openshorts_runtime_once(
                config,
                now="2026-09-14T14:00:00+00:00",
                transport=object(),
            )

            self.assertTrue(Path(db_path).exists())

        self.assertEqual(1, result.completed)
        kwargs = run_cycle.call_args.kwargs
        self.assertEqual(2, kwargs["max_jobs"])
        self.assertEqual("openshorts-worker-1", kwargs["worker_id"])
        self.assertEqual("2026-09-14T14:00:00+00:00", kwargs["now"])
        self.assertTrue(kwargs["credential_authority_verified"])
        self.assertTrue(kwargs["cost_authority_verified"])
        self.assertEqual("osk_test_key_12345", kwargs["api_key"])
        self.assertEqual("s" * 32, kwargs["webhook_secret"])


if __name__ == "__main__":
    unittest.main()
