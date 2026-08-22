from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.durable_side_effect_binding import (
    DurableSideEffectBinding,
    DurableSideEffectBindingLedger,
    reconcile_bound_job_from_side_effect,
)
from workflow_os.job_queue import JobQueue
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-08-22T20:00:00+00:00"


class DurableSideEffectBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableSideEffectBindingLedger(root / "bindings.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _leased(self):
        job = self.queue.enqueue(
            idempotency_key="job-1",
            opportunity_id="opp-1",
            job_type="produce_and_publish",
            payload={"opportunity_id": "opp-1"},
            available_at=NOW,
            max_attempts=3,
        )
        return self.queue.claim(worker_id="worker-1", now=NOW, lease_seconds=300) or job

    def _binding(self, job, effect):
        return DurableSideEffectBinding(
            job_id=job.job_id,
            job_request_fingerprint=job.request_fingerprint,
            opportunity_id=job.opportunity_id,
            side_effect_idempotency_key=effect.idempotency_key,
            side_effect_request_fingerprint=effect.request_fingerprint,
        )

    def _effect(self):
        return self.effects.reserve(
            idempotency_key="publish-1",
            action="publish_submission",
            target="https://www.tiktok.com/",
            payload={"opportunity_id": "opp-1"},
            max_attempts=3,
        )

    def test_succeeded_side_effect_completes_job(self):
        job = self._leased()
        effect = self._effect()
        self.effects.begin_attempt(effect.idempotency_key)
        self.effects.mark_succeeded(effect.idempotency_key, external_reference="post-1")
        result = reconcile_bound_job_from_side_effect(
            self.queue, self._binding(job, effect), worker_id="worker-1", now=NOW,
            side_effect_ledger=self.effects,
        )
        self.assertEqual("SUCCEEDED", result.state)

    def test_proven_not_applied_is_retry_safe(self):
        job = self._leased()
        effect = self._effect()
        self.effects.begin_attempt(effect.idempotency_key)
        self.effects.mark_failed(effect.idempotency_key, definitely_not_applied=True)
        result = reconcile_bound_job_from_side_effect(
            self.queue, self._binding(job, effect), worker_id="worker-1", now=NOW,
            side_effect_ledger=self.effects,
        )
        self.assertEqual("FAILED_RETRYABLE", result.state)

    def test_unknown_side_effect_makes_job_unknown(self):
        job = self._leased()
        effect = self._effect()
        self.effects.begin_attempt(effect.idempotency_key)
        self.effects.mark_failed(effect.idempotency_key, definitely_not_applied=False)
        result = reconcile_bound_job_from_side_effect(
            self.queue, self._binding(job, effect), worker_id="worker-1", now=NOW,
            side_effect_ledger=self.effects,
        )
        self.assertEqual("UNKNOWN", result.state)

    def test_nonterminal_side_effect_is_not_guessed(self):
        job = self._leased()
        effect = self._effect()
        with self.assertRaisesRegex(RuntimeError, "not terminal"):
            reconcile_bound_job_from_side_effect(
                self.queue, self._binding(job, effect), worker_id="worker-1", now=NOW,
                side_effect_ledger=self.effects,
            )

    def test_fingerprint_drift_fails_closed(self):
        job = self._leased()
        effect = self._effect()
        bad = DurableSideEffectBinding(
            job_id=job.job_id,
            job_request_fingerprint=job.request_fingerprint,
            opportunity_id=job.opportunity_id,
            side_effect_idempotency_key=effect.idempotency_key,
            side_effect_request_fingerprint="0" * 64,
        )
        with self.assertRaisesRegex(RuntimeError, "fingerprint changed"):
            reconcile_bound_job_from_side_effect(
                self.queue, bad, worker_id="worker-1", now=NOW,
                side_effect_ledger=self.effects,
            )

    def test_binding_ledger_round_trip(self):
        binding = DurableSideEffectBinding(1, "a" * 64, "opp-1", "publish-1", "b" * 64)
        with self.bindings._connect() as db:
            db.execute(
                "INSERT INTO durable_side_effect_bindings(job_id,job_request_fingerprint,opportunity_id,side_effect_idempotency_key,side_effect_request_fingerprint) VALUES(?,?,?,?,?)",
                (binding.job_id, binding.job_request_fingerprint, binding.opportunity_id,
                 binding.side_effect_idempotency_key, binding.side_effect_request_fingerprint),
            )
        self.assertEqual(binding, self.bindings.get(1))


if __name__ == "__main__":
    unittest.main()
