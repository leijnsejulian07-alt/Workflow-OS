import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.side_effect_recovery import recover_orphaned_execution
from workflow_os.side_effects import SideEffectLedger


class SideEffectRecoveryTests(unittest.TestCase):
    def make_ledger(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "workflow-os.sqlite3"
        return path, SideEffectLedger(path)

    def executing(self, key="publish:crash", *, max_attempts=3):
        path, ledger = self.make_ledger()
        ledger.reserve(idempotency_key=key, action="publish", target="platform:account", payload={"asset": "x"}, max_attempts=max_attempts)
        ledger.begin_attempt(key)
        return path, ledger

    def set_updated_at(self, path, key, value):
        with managed_connection(sqlite3.connect(path)) as db:
            db.execute("UPDATE side_effects SET updated_at=? WHERE idempotency_key=?", (value, key))

    def test_fresh_execution_cannot_be_stolen_or_retried(self):
        path, ledger = self.executing()
        now = datetime.now(timezone.utc)
        self.set_updated_at(path, "publish:crash", now.strftime("%Y-%m-%d %H:%M:%S"))
        result = recover_orphaned_execution(path, "publish:crash", now=now, stale_after_seconds=900)
        self.assertFalse(result.recovered)
        self.assertEqual("EXECUTING", result.state)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("publish:crash")

    def test_stale_execution_becomes_unknown_only(self):
        path, ledger = self.executing()
        now = datetime.now(timezone.utc)
        stale = now - timedelta(hours=1)
        self.set_updated_at(path, "publish:crash", stale.strftime("%Y-%m-%d %H:%M:%S"))
        result = recover_orphaned_execution(path, "publish:crash", now=now, stale_after_seconds=900)
        self.assertTrue(result.recovered)
        self.assertEqual("UNKNOWN", result.state)
        self.assertEqual(1, ledger.get("publish:crash").attempt_count)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("publish:crash")

    def test_malformed_or_future_freshness_fails_closed_to_unknown(self):
        for stamp in ("garbage", "2999-01-01 00:00:00"):
            with self.subTest(stamp=stamp):
                path, ledger = self.executing(key="deploy:crash")
                self.set_updated_at(path, "deploy:crash", stamp)
                result = recover_orphaned_execution(path, "deploy:crash", now=datetime.now(timezone.utc))
                self.assertEqual("UNKNOWN", result.state)
                self.assertEqual(1, ledger.get("deploy:crash").attempt_count)

    def test_recovery_is_idempotent_and_reconciliation_controls_retry(self):
        path, ledger = self.executing(max_attempts=2)
        now = datetime.now(timezone.utc)
        self.set_updated_at(path, "publish:crash", (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
        first = recover_orphaned_execution(path, "publish:crash", now=now)
        second = recover_orphaned_execution(path, "publish:crash", now=now)
        self.assertTrue(first.recovered)
        self.assertFalse(second.recovered)
        self.assertEqual("UNKNOWN", second.state)
        ledger.reconcile_not_applied("publish:crash")
        retry = ledger.begin_attempt("publish:crash")
        self.assertEqual(2, retry.attempt_count)
        ledger.mark_failed("publish:crash", definitely_not_applied=True)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("publish:crash")

    def test_unknown_can_reconcile_to_success_without_retry(self):
        path, ledger = self.executing(key="deploy:crash")
        now = datetime.now(timezone.utc)
        self.set_updated_at(path, "deploy:crash", (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
        recover_orphaned_execution(path, "deploy:crash", now=now)
        success = ledger.mark_succeeded("deploy:crash", external_reference="deployment-123")
        self.assertEqual("SUCCEEDED", success.state)
        self.assertEqual(1, success.attempt_count)

    def test_non_executing_state_is_not_mutated(self):
        path, ledger = self.make_ledger()
        ledger.reserve(idempotency_key="reserved:1", action="create", target="provider:object", payload={})
        result = recover_orphaned_execution(path, "reserved:1", now=datetime.now(timezone.utc))
        self.assertFalse(result.recovered)
        self.assertEqual("RESERVED", result.state)

    def test_recovery_inputs_are_bounded(self):
        path, _ = self.executing()
        with self.assertRaises(ValueError):
            recover_orphaned_execution(path, "publish:crash", now=datetime.now(), stale_after_seconds=900)
        with self.assertRaises(ValueError):
            recover_orphaned_execution(path, "publish:crash", now=datetime.now(timezone.utc), stale_after_seconds=0)
        with self.assertRaises(ValueError):
            recover_orphaned_execution(path, "publish:crash", now=datetime.now(timezone.utc), stale_after_seconds=86_401)


if __name__ == "__main__":
    unittest.main()
