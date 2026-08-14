import tempfile
import unittest
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger


class SideEffectLedgerTests(unittest.TestCase):
    def make_ledger(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return SideEffectLedger(Path(temp.name) / "workflow-os.sqlite3")

    def test_same_key_same_request_is_idempotent(self):
        ledger = self.make_ledger()
        first = ledger.reserve(
            idempotency_key="publish:abc:1",
            action="publish",
            target="youtube:channel-1",
            payload={"video_id": "abc"},
        )
        second = ledger.reserve(
            idempotency_key="publish:abc:1",
            action="publish",
            target="youtube:channel-1",
            payload={"video_id": "abc"},
        )
        self.assertEqual(first.request_fingerprint, second.request_fingerprint)
        self.assertEqual("RESERVED", second.state)

    def test_same_key_different_request_is_rejected(self):
        ledger = self.make_ledger()
        ledger.reserve(
            idempotency_key="deploy:job-1",
            action="deploy",
            target="site:customer-1",
            payload={"artifact": "a"},
        )
        with self.assertRaises(ValueError):
            ledger.reserve(
                idempotency_key="deploy:job-1",
                action="deploy",
                target="site:customer-1",
                payload={"artifact": "b"},
            )

    def test_ambiguous_failure_blocks_blind_retry_until_reconciled(self):
        ledger = self.make_ledger()
        ledger.reserve(
            idempotency_key="publish:x",
            action="publish",
            target="platform:account",
            payload={"asset": "x"},
        )
        ledger.begin_attempt("publish:x")
        unknown = ledger.mark_failed("publish:x", definitely_not_applied=False)
        self.assertEqual("UNKNOWN", unknown.state)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("publish:x")

        retryable = ledger.reconcile_not_applied("publish:x")
        self.assertEqual("FAILED_RETRYABLE", retryable.state)
        retry = ledger.begin_attempt("publish:x")
        self.assertEqual(2, retry.attempt_count)
        self.assertEqual("EXECUTING", retry.state)

    def test_definitive_failure_can_retry_with_bounded_budget(self):
        ledger = self.make_ledger()
        ledger.reserve(
            idempotency_key="create:1",
            action="create",
            target="provider:object",
            payload={},
            max_attempts=2,
        )
        ledger.begin_attempt("create:1")
        ledger.mark_failed("create:1", definitely_not_applied=True)
        ledger.begin_attempt("create:1")
        ledger.mark_failed("create:1", definitely_not_applied=True)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("create:1")

    def test_success_is_terminal_and_idempotent(self):
        ledger = self.make_ledger()
        ledger.reserve(
            idempotency_key="pay:1",
            action="pay",
            target="provider:invoice",
            payload={"amount": "10.00"},
        )
        ledger.begin_attempt("pay:1")
        success = ledger.mark_succeeded("pay:1", external_reference="ext-123")
        self.assertEqual("SUCCEEDED", success.state)
        again = ledger.mark_succeeded("pay:1", external_reference="ext-123")
        self.assertEqual("SUCCEEDED", again.state)
        with self.assertRaises(RuntimeError):
            ledger.begin_attempt("pay:1")
        with self.assertRaises(ValueError):
            ledger.mark_succeeded("pay:1", external_reference="ext-other")

    def test_unknown_can_reconcile_to_success_without_retry(self):
        ledger = self.make_ledger()
        ledger.reserve(
            idempotency_key="deploy:2",
            action="deploy",
            target="hosting:site",
            payload={"version": 2},
        )
        ledger.begin_attempt("deploy:2")
        ledger.mark_failed("deploy:2", definitely_not_applied=False)
        success = ledger.mark_succeeded("deploy:2", external_reference="deployment-2")
        self.assertEqual("SUCCEEDED", success.state)
        self.assertEqual(1, success.attempt_count)

    def test_payload_and_retry_limits_are_bounded(self):
        ledger = self.make_ledger()
        with self.assertRaises(ValueError):
            ledger.reserve(
                idempotency_key="oversize",
                action="publish",
                target="platform:account",
                payload={"data": "x" * (65 * 1024)},
            )
        with self.assertRaises(ValueError):
            ledger.reserve(
                idempotency_key="too-many-retries",
                action="publish",
                target="platform:account",
                payload={},
                max_attempts=11,
            )


if __name__ == "__main__":
    unittest.main()
