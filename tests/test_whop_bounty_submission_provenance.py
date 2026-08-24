import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.adapters.whop_bounty_submission import WHOP_BOUNTY_SUBMISSION_URL
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBinding
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger


class WhopBountySubmissionProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.side_effects = SideEffectLedger(root / "side-effects.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        self.side_effect = self.side_effects.reserve(
            idempotency_key="whop-bounty:job-0001",
            action="submit_whop_bounty",
            target=WHOP_BOUNTY_SUBMISSION_URL,
            payload={"bounty_id": "bnty_example123", "deliverable": {"type": "content_url"}},
            max_attempts=3,
        )
        self.binding = DurableWhopBountyBinding(
            job_id=1,
            job_request_fingerprint="1" * 64,
            opportunity_id="opp-whop-1",
            bounty_id="bnty_example123",
            side_effect_idempotency_key=self.side_effect.idempotency_key,
            side_effect_request_fingerprint=self.side_effect.request_fingerprint,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _succeed(self, reference="btys_submission123"):
        self.side_effects.begin_attempt(self.side_effect.idempotency_key)
        return self.side_effects.mark_succeeded(
            self.side_effect.idempotency_key,
            external_reference=reference,
        )

    def test_records_confirmed_submission_against_exact_opportunity(self):
        self._succeed()
        record = self.provenance.record_confirmed_submission(
            self.binding,
            side_effect_ledger=self.side_effects,
        )
        self.assertEqual(record.opportunity_id, "opp-whop-1")
        self.assertEqual(record.bounty_id, "bnty_example123")
        self.assertEqual(record.submission_reference, "btys_submission123")
        self.assertEqual(self.provenance.get_by_reference("btys_submission123"), record)

    def test_exact_replay_is_idempotent(self):
        self._succeed()
        first = self.provenance.record_confirmed_submission(
            self.binding,
            side_effect_ledger=self.side_effects,
        )
        second = self.provenance.record_confirmed_submission(
            self.binding,
            side_effect_ledger=self.side_effects,
        )
        self.assertEqual(first, second)

    def test_rejects_nonterminal_submission(self):
        with self.assertRaisesRegex(RuntimeError, "confirmed SUCCEEDED"):
            self.provenance.record_confirmed_submission(
                self.binding,
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_side_effect_fingerprint_drift(self):
        self._succeed()
        drifted = replace(self.binding, side_effect_request_fingerprint="f" * 64)
        with self.assertRaisesRegex(RuntimeError, "fingerprint changed"):
            self.provenance.record_confirmed_submission(
                drifted,
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_wrong_action_even_if_succeeded(self):
        other = self.side_effects.reserve(
            idempotency_key="publish:job-0002",
            action="publish_submission",
            target="https://example.com/publish",
            payload={"x": 1},
            max_attempts=1,
        )
        self.side_effects.begin_attempt(other.idempotency_key)
        self.side_effects.mark_succeeded(other.idempotency_key, external_reference="btys_fake123")
        binding = replace(
            self.binding,
            side_effect_idempotency_key=other.idempotency_key,
            side_effect_request_fingerprint=other.request_fingerprint,
        )
        with self.assertRaisesRegex(RuntimeError, "only for Whop bounty submissions"):
            self.provenance.record_confirmed_submission(
                binding,
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_malformed_success_reference(self):
        self._succeed(reference="not-a-whop-submission")
        with self.assertRaisesRegex(RuntimeError, "reference is malformed"):
            self.provenance.record_confirmed_submission(
                self.binding,
                side_effect_ledger=self.side_effects,
            )

    def test_one_submission_reference_cannot_bind_two_side_effects(self):
        self._succeed()
        self.provenance.record_confirmed_submission(
            self.binding,
            side_effect_ledger=self.side_effects,
        )
        second = self.side_effects.reserve(
            idempotency_key="whop-bounty:job-0002",
            action="submit_whop_bounty",
            target=WHOP_BOUNTY_SUBMISSION_URL,
            payload={"bounty_id": "bnty_example123", "deliverable": {"type": "content_url", "n": 2}},
            max_attempts=3,
        )
        self.side_effects.begin_attempt(second.idempotency_key)
        with self.assertRaisesRegex(ValueError, "already bound to another side effect"):
            self.side_effects.mark_succeeded(
                second.idempotency_key,
                external_reference="btys_submission123",
            )

    def test_submission_success_is_not_cash_evidence(self):
        self._succeed()
        record = self.provenance.record_confirmed_submission(
            self.binding,
            side_effect_ledger=self.side_effects,
        )
        self.assertFalse(hasattr(record, "amount_eur"))
        self.assertFalse(hasattr(record, "proves_received_cash"))


if __name__ == "__main__":
    unittest.main()
