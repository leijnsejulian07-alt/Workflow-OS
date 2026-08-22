from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.durable_side_effect_binding import DurableSideEffectBinding
from workflow_os.publication_provenance import PublicationProvenanceLedger
from workflow_os.side_effects import SideEffectLedger


class PublicationProvenanceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.provenance = PublicationProvenanceLedger(root / "provenance.sqlite")
        reserved = self.effects.reserve(
            idempotency_key="publish-1",
            action="publish_submission",
            target="https://www.tiktok.com/",
            payload={"opportunity_id": "opp-1"},
            max_attempts=3,
        )
        self.binding = DurableSideEffectBinding(
            job_id=1,
            job_request_fingerprint="a" * 64,
            opportunity_id="opp-1",
            side_effect_idempotency_key=reserved.idempotency_key,
            side_effect_request_fingerprint=reserved.request_fingerprint,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _succeed(self, reference: str = "post-1") -> None:
        self.effects.begin_attempt("publish-1")
        self.effects.mark_succeeded("publish-1", external_reference=reference)

    def test_confirmed_publication_is_bound_to_opportunity(self):
        self._succeed()
        recorded = self.provenance.record_confirmed_publication(
            self.binding,
            side_effect_ledger=self.effects,
        )
        self.assertEqual("opp-1", recorded.opportunity_id)
        self.assertEqual("post-1", recorded.publication_reference)
        self.assertEqual(
            recorded,
            self.provenance.get_by_reference("https://www.tiktok.com/", "post-1"),
        )

    def test_exact_replay_is_idempotent(self):
        self._succeed()
        first = self.provenance.record_confirmed_publication(
            self.binding,
            side_effect_ledger=self.effects,
        )
        second = self.provenance.record_confirmed_publication(
            self.binding,
            side_effect_ledger=self.effects,
        )
        self.assertEqual(first, second)

    def test_nonterminal_publication_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "confirmed SUCCEEDED"):
            self.provenance.record_confirmed_publication(
                self.binding,
                side_effect_ledger=self.effects,
            )

    def test_success_without_external_reference_is_rejected(self):
        self.effects.begin_attempt("publish-1")
        self.effects.mark_succeeded("publish-1")
        with self.assertRaisesRegex(RuntimeError, "stable external reference"):
            self.provenance.record_confirmed_publication(
                self.binding,
                side_effect_ledger=self.effects,
            )

    def test_fingerprint_drift_is_rejected(self):
        self._succeed()
        drifted = DurableSideEffectBinding(
            job_id=1,
            job_request_fingerprint="a" * 64,
            opportunity_id="opp-1",
            side_effect_idempotency_key="publish-1",
            side_effect_request_fingerprint="b" * 64,
        )
        with self.assertRaisesRegex(RuntimeError, "fingerprint changed"):
            self.provenance.record_confirmed_publication(
                drifted,
                side_effect_ledger=self.effects,
            )

    def test_duplicate_external_reference_for_same_target_is_rejected(self):
        self._succeed("post-1")
        self.provenance.record_confirmed_publication(
            self.binding,
            side_effect_ledger=self.effects,
        )

        second = self.effects.reserve(
            idempotency_key="publish-2",
            action="publish_submission",
            target="https://www.tiktok.com/",
            payload={"opportunity_id": "opp-2"},
            max_attempts=3,
        )
        self.effects.begin_attempt("publish-2")
        # SideEffectLedger itself protects this same action/target/reference identity.
        with self.assertRaises(ValueError):
            self.effects.mark_succeeded("publish-2", external_reference="post-1")
        self.assertEqual("EXECUTING", self.effects.get(second.idempotency_key).state)


if __name__ == "__main__":
    unittest.main()
